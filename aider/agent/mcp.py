"""MCP (Model Context Protocol) istemcisi.

Harici MCP sunucularını stdio üzerinden başlatır, sundukları araçları keşfeder
ve agent'ın araç kayıt defterine ekler. Sunucu araçları
`mcp__<sunucu>__<araç>` adıyla görünür, böylece yerleşik araçlarla çakışmaz.

Bağımlılık eklememek için resmi MCP SDK'sı yerine satır bazlı JSON-RPC 2.0
konuşan küçük ve senkron bir istemci kullanılıyor; aider'ın gövdesi senkron
olduğu için async bir istemci köprülemek gereksiz karmaşıklık getirirdi.

Yapılandırma, Claude Code ile aynı biçimde `.mcp.json` dosyasından okunur.
İki taşıma destekleniyor — hangisinin kullanılacağı alanlardan anlaşılır:

    {
      "mcpServers": {
        "postgres": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-postgres", "postgres://..."],
          "env": {"PGPASSWORD": "..."}
        },
        "satellite": {
          "url": "http://localhost:8080/mcp/sse",
          "headers": {"FOREMAN_USERNAME": "...", "FOREMAN_TOKEN": "..."},
          "tools": ["hosts_list", "host_details"]
        }
      }
    }

`url` verilen sunucuya streamable HTTP ile bağlanılır. Bu şart: Red Hat'in
Satellite MCP sunucusu ve SUSE'nin Rancher MCP sunucusu yalnızca HTTP
konuşuyor, yani stdio-only bir istemci onlara hiç bağlanamıyor.

`tools` verilirse yalnızca o araçlar modele sunulur. Bu da şart, çünkü araç
şemaları HER isteğe giriyor: ölçüldü, 16k pencereli bir modelde sekiz MCP
aracı pencerenin dörtte birini, on altısı yarısına yakınını yiyor. Sunucuların
kendi `--toolsets` bayrakları takım düzeyinde kısıyor, tek tek araç
seçtirmiyor.
"""

import atexit
import ipaddress
import json
import os
import queue
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .registry import ToolError
from .tools import Tool, _truncate

PROTOCOL_VERSION = "2024-11-05"

# Sunucu başlatma ve tek bir isteğin yanıtı için tavan süreler.
STARTUP_TIMEOUT = 30
REQUEST_TIMEOUT = 120

CONFIG_NAMES = (".mcp.json", ".aider/mcp.json")

# Paketi çalıştırmadan önce ağdan indiren başlatıcılar. Çevrimdışı bir
# sunucuda bunlar sessizce takılıp STARTUP_TIMEOUT boyunca bekletiyor;
# belirtisi "aider açılmıyor" oluyor, sebebi görünmüyor.
AG_INDIREN_KOMUTLAR = ("npx", "uvx", "bunx", "pnpx", "pipx")


class MCPError(Exception):
    """MCP sunucusuyla konuşurken oluşan hata."""


class MCPServer:
    """Tek bir MCP sunucu sürecini yönetir."""

    def __init__(self, name, command, args=None, env=None, cwd=None):
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.cwd = cwd
        self.proc = None
        self.tools = []
        self._next_id = 0
        self._lock = threading.Lock()
        # Okuyucu iş parçacığı stdout'u sürekli tüketir ve ayrıştırılmış
        # mesajları buraya bırakır. readline() bloke ettiği için zaman aşımı
        # ancak bu şekilde gerçekten uygulanabiliyor.
        self._inbox = queue.Queue()
        self._reader = None
        # Sunucunun stderr'i geçici bir dosyaya yazılıyor. DEVNULL'a
        # gönderildiğinde başlatma hatasının SEBEBİ kayboluyor ve kullanıcı
        # yalnızca "başlatılamadı" görüyor; çevrimdışı bir sunucuda bunu
        # teşhis etmek çok zor. Boru yerine dosya: kimse okumazsa boru
        # dolduğunda sunucu bloke oluyor.
        self._stderr_dosyasi = None

    # -- süreç yaşam döngüsü -------------------------------------------------

    def start(self):
        """Sunucuyu başlat, el sıkış ve araçlarını keşfet."""
        full_env = os.environ.copy()
        full_env.update(self.env)

        try:
            self._stderr_dosyasi = tempfile.TemporaryFile(
                mode="w+", encoding="utf-8", errors="replace"
            )
        except OSError:
            self._stderr_dosyasi = None

        try:
            self.proc = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_dosyasi or subprocess.DEVNULL,
                env=full_env,
                cwd=self.cwd,
                text=True,
                bufsize=1,
            )
        except (OSError, ValueError) as err:
            raise MCPError(f"'{self.command}' başlatılamadı: {err}")

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "aider-agent", "version": "1"},
                },
                timeout=STARTUP_TIMEOUT,
            )
            self._notify("notifications/initialized")

            result = self._request("tools/list", {}, timeout=STARTUP_TIMEOUT)
        except MCPError as err:
            # Sebebi sunucunun kendi hata çıktısında; onsuz teşhis edilemiyor.
            raise MCPError(str(err) + self._stderr_ipucu())

        self.tools = result.get("tools", []) or []
        return self.tools

    def _stderr_ipucu(self, satir=8):
        """Sunucunun son hata satırları; hata mesajına eklenir."""
        if not self._stderr_dosyasi:
            return ""
        try:
            self._stderr_dosyasi.seek(0)
            satirlar = self._stderr_dosyasi.read().strip().splitlines()
        except (OSError, ValueError):
            return ""
        if not satirlar:
            return ""
        return "\n    sunucu çıktısı: " + " | ".join(s.strip() for s in satirlar[-satir:])

    def stop(self):
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        except OSError:
            pass
        finally:
            self.proc = None
            if self._stderr_dosyasi:
                try:
                    self._stderr_dosyasi.close()
                except OSError:
                    pass
                self._stderr_dosyasi = None

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

    # -- JSON-RPC ------------------------------------------------------------

    def _send(self, payload):
        if not self.is_alive():
            raise MCPError(f"'{self.name}' sunucusu çalışmıyor")
        try:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as err:
            raise MCPError(f"'{self.name}' sunucusuna yazılamadı: {err}")

    def _notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _read_loop(self):
        """Arka planda stdout'u tüket ve ayrıştırılmış mesajları kuyruğa koy."""
        stdout = self.proc.stdout
        try:
            for line in stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._inbox.put(json.loads(line))
                except json.JSONDecodeError:
                    # Sunucu stdout'a JSON olmayan bir şey yazmış; yoksay.
                    continue
        except (ValueError, OSError):
            # Süreç kapatılırken boru kapanabilir; sessizce çık.
            pass
        finally:
            # Bekleyen bir istek varsa sonsuza dek beklemesin.
            self._inbox.put(None)

    def _request(self, method, params, timeout=REQUEST_TIMEOUT):
        """İstek gönder ve eşleşen kimlikli yanıtı bekle."""
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPError(
                        f"'{self.name}' sunucusu {timeout} saniyede yanıt vermedi ({method})"
                    )
                try:
                    msg = self._inbox.get(timeout=remaining)
                except queue.Empty:
                    continue

                if msg is None:
                    raise MCPError(f"'{self.name}' sunucusu beklenmedik şekilde kapandı")

                # Bildirimlerin id'si yoktur; yalnızca kendi yanıtımızı bekliyoruz.
                if msg.get("id") != req_id:
                    continue

                if "error" in msg:
                    err = msg["error"]
                    raise MCPError(f"{err.get('code')}: {err.get('message')}")
                return msg.get("result", {})

    def call_tool(self, tool_name, arguments):
        return _sonuc_metni(
            self._request("tools/call", {"name": tool_name, "arguments": arguments})
        )


def _sonuc_metni(result):
    """`tools/call` yanıtını düz metne çevir; iki taşıma da bunu kullanır."""
    parts = []
    for item in result.get("content", []) or []:
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
        else:
            parts.append(f"[{item.get('type')} içeriği döndü]")

    text = "\n".join(p for p in parts if p) or "(sunucu boş yanıt döndü)"
    if result.get("isError"):
        return f"Hata: {text}"
    return text


def yerel_adres_mi(url):
    """Adres yerel ağda mı? Çevrimdışı modda dışarı çıkmayı engellemek için.

    Ad çözülemezse HAYIR sayılıyor: doğrulanamayan bir adrese hava boşluklu
    ortamda istek atmak, o ortamın varlık sebebine aykırı.
    """
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        adresler = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    for aile in adresler:
        try:
            ip = ipaddress.ip_address(aile[4][0])
        except ValueError:
            return False
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            return False
    return bool(adresler)


class MCPHttpSunucu:
    """Streamable HTTP üzerinden konuşan MCP sunucusu.

    Süreç yönetmiyor: sunucu zaten ayakta, biz yalnızca POST atıyoruz. Yanıt
    ya düz JSON ya da SSE akışı olabiliyor; şartname ikisine de izin verdiği
    için ikisi de ayrıştırılıyor.

    Oturum kimliği (`Mcp-Session-Id`) initialize yanıtında gelirse sonraki
    her isteğe geri konuyor; koymayan istemcileri bazı sunucular reddediyor.
    """

    def __init__(self, name, url, headers=None, timeout=REQUEST_TIMEOUT):
        self.name = name
        self.url = url
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.tools = []
        self.oturum = None
        self._next_id = 0
        self._lock = threading.Lock()
        self._acik = False

    # -- yaşam döngüsü -------------------------------------------------------

    def start(self):
        self._acik = True
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "aider-agent", "version": "1"},
                },
                timeout=STARTUP_TIMEOUT,
            )
            self._notify("notifications/initialized")
            result = self._request("tools/list", {}, timeout=STARTUP_TIMEOUT)
        except MCPError:
            self._acik = False
            raise

        self.tools = result.get("tools", []) or []
        return self.tools

    def stop(self):
        self._acik = False
        self.oturum = None

    def is_alive(self):
        return self._acik

    # -- JSON-RPC over HTTP --------------------------------------------------

    def _gonder(self, govde, timeout):
        basliklar = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        basliklar.update(self.headers)
        if self.oturum:
            basliklar["Mcp-Session-Id"] = self.oturum

        istek = urllib.request.Request(
            self.url,
            data=json.dumps(govde).encode("utf-8"),
            headers=basliklar,
            method="POST",
        )
        try:
            with urllib.request.urlopen(istek, timeout=timeout) as yanit:
                oturum = yanit.headers.get("Mcp-Session-Id")
                if oturum:
                    self.oturum = oturum
                govde_metni = yanit.read().decode("utf-8", "replace")
                tur = (yanit.headers.get("Content-Type") or "").lower()
        except urllib.error.HTTPError as err:
            detay = ""
            try:
                detay = " — " + err.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise MCPError(f"'{self.name}' HTTP {err.code}{detay}")
        except (urllib.error.URLError, OSError) as err:
            raise MCPError(f"'{self.name}' adresine ulaşılamadı: {err}")

        return govde_metni, tur

    @staticmethod
    def _sse_ayikla(metin):
        """SSE gövdesindeki `data:` satırlarını JSON nesnelerine çevir."""
        out = []
        for satir in metin.splitlines():
            satir = satir.strip()
            if not satir.startswith("data:"):
                continue
            veri = satir[len("data:") :].strip()
            if not veri or veri == "[DONE]":
                continue
            try:
                out.append(json.loads(veri))
            except json.JSONDecodeError:
                continue
        return out

    def _mesajlar(self, govde_metni, tur):
        if "text/event-stream" in tur:
            return self._sse_ayikla(govde_metni)
        if not govde_metni.strip():
            return []
        try:
            veri = json.loads(govde_metni)
        except json.JSONDecodeError:
            # Bazı sunucular Content-Type'ı yanlış bildiriyor; SSE olarak dene.
            return self._sse_ayikla(govde_metni)
        return veri if isinstance(veri, list) else [veri]

    def _notify(self, method, params=None):
        if not self._acik:
            return
        try:
            self._gonder({"jsonrpc": "2.0", "method": method, "params": params or {}}, self.timeout)
        except MCPError:
            # Bildirim yanıtsızdır; başarısızlığı oturumu düşürmemeli.
            pass

    def _request(self, method, params, timeout=None):
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            govde_metni, tur = self._gonder(
                {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
                timeout or self.timeout,
            )

        for msg in self._mesajlar(govde_metni, tur):
            if msg.get("id") != req_id:
                continue
            if "error" in msg:
                err = msg["error"]
                raise MCPError(f"{err.get('code')}: {err.get('message')}")
            return msg.get("result", {})

        raise MCPError(f"'{self.name}' sunucusundan {method} için yanıt gelmedi")

    def call_tool(self, tool_name, arguments):
        return _sonuc_metni(
            self._request("tools/call", {"name": tool_name, "arguments": arguments})
        )


class MCPTool(Tool):
    """Uzak bir MCP aracını yerel araç arayüzüne uyarlar."""

    # MCP araçlarının yan etkisi olup olmadığı bilinmez; güvenli taraf onay
    # istemektir. readOnlyHint veren sunucularda bu aşağıda gevşetiliyor.
    mutating = True

    def __init__(self, server, spec):
        self.server = server
        self.remote_name = spec["name"]
        self.name = f"mcp__{server.name}__{spec['name']}"
        self.description = spec.get("description") or f"{server.name} MCP aracı"
        self.parameters = spec.get("inputSchema") or {"type": "object", "properties": {}}

        hints = spec.get("annotations") or {}
        if hints.get("readOnlyHint") is True:
            self.mutating = False

    def run(self, ctx, **kwargs):
        if self.mutating:
            subject = f"{self.server.name}: {self.remote_name}"
            detail = json.dumps(kwargs, ensure_ascii=False)[:300]
            if not ctx.confirm(
                self.name, f"{subject}\n  {detail}", "MCP aracını çalıştır?", args=kwargs
            ):
                return "Kullanıcı bu MCP aracını reddetti."

        try:
            return _truncate(self.server.call_tool(self.remote_name, kwargs))
        except MCPError as err:
            raise ToolError(str(err))


def find_config(project_root):
    """Proje kökünde MCP yapılandırma dosyasını bul."""
    for name in CONFIG_NAMES:
        path = Path(project_root) / name
        if path.is_file():
            return path
    return None


def read_config(path):
    """MCP yapılandırmasını oku ve sunucu tanımlarını döndür."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise MCPError(f"{path} okunamadı: {err}")

    servers = data.get("mcpServers")
    if servers is None:
        raise MCPError(f"{path}: 'mcpServers' anahtarı yok")
    if not isinstance(servers, dict):
        raise MCPError(f"{path}: 'mcpServers' bir nesne olmalı")

    out = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            raise MCPError(f"{path}: '{name}' sunucusu bir nesne olmalı")
        if not cfg.get("command") and not cfg.get("url"):
            raise MCPError(f"{path}: '{name}' sunucusunda 'command' ya da 'url' olmalı")
        if cfg.get("command") and cfg.get("url"):
            raise MCPError(
                f"{path}: '{name}' hem 'command' hem 'url' veriyor; hangi taşımanın"
                " kullanılacağı belirsiz kalır"
            )
        araclar = cfg.get("tools")
        if araclar is not None and not (
            isinstance(araclar, list) and all(isinstance(a, str) for a in araclar)
        ):
            raise MCPError(f"{path}: '{name}' içindeki 'tools' bir dize listesi olmalı")
        out[name] = cfg
    return out


class MCPManager:
    """Yapılandırılmış tüm MCP sunucularını yönetir."""

    def __init__(self, io, project_root, offline=False):
        self.io = io
        self.project_root = project_root
        self.offline = offline
        self.servers = {}
        self.tools = []
        self.errors = []
        # Aider'ın coder'lar için net bir teardown kancası yok; süreçlerin
        # oturum sonunda arkada kalmaması için çıkışa bağlanıyoruz.
        atexit.register(self.shutdown)

    def load(self):
        """Yapılandırmayı oku, sunucuları başlat, araçları topla.

        Bir sunucunun başlatılamaması oturumu düşürmez; hata kaydedilir ve
        diğer sunucularla devam edilir.
        """
        self.tools = []
        self.errors = []

        path = find_config(self.project_root)
        if not path:
            return self.tools

        try:
            configs = read_config(path)
        except MCPError as err:
            self.errors.append(str(err))
            return self.tools

        for name, cfg in configs.items():
            server = self._sunucu_kur(name, cfg)
            if server is None:
                continue

            try:
                specs = server.start()
            except MCPError as err:
                server.stop()
                self.errors.append(f"{name}: {err}")
                continue

            self.servers[name] = server
            for spec in self._secilenler(name, specs, cfg.get("tools")):
                self.tools.append(MCPTool(server, spec))

        return self.tools

    def _sunucu_kur(self, name, cfg):
        """Yapılandırmadan taşımayı seç. Başlatılmayacaksa None döner."""
        if cfg.get("url"):
            if self.offline and not yerel_adres_mi(cfg["url"]):
                self.errors.append(
                    f"{name}: '{cfg['url']}' yerel ağda değil (ya da adı çözülemedi),"
                    " çevrimdışı modda bağlanılmadı."
                )
                return None
            return MCPHttpSunucu(name=name, url=cfg["url"], headers=cfg.get("headers"))

        if self.offline and cfg["command"] in AG_INDIREN_KOMUTLAR:
            self.errors.append(
                f"{name}: '{cfg['command']}' paketi ağdan indirir, çevrimdışı modda"
                " başlatılmadı. Paketi önceden kurup 'command' alanına doğrudan"
                " çalıştırılabilir yolu yaz."
            )
            return None

        return MCPServer(
            name=name,
            command=cfg["command"],
            args=cfg.get("args"),
            env=cfg.get("env"),
            cwd=cfg.get("cwd") or self.project_root,
        )

    def _secilenler(self, name, specs, beyaz_liste):
        """Beyaz liste verilmişse yalnızca oradaki araçları sun.

        Sebep ölçülü: araç şemaları her isteğe giriyor ve 16k pencereli bir
        modelde on altı araç pencerenin yarısına yakınını yiyor. Beyaz listede
        olup sunucuda olmayan ad sessizce yutulmuyor — yazım hatası, aracın
        neden görünmediğini saatlerce aratır.
        """
        gecerli = [s for s in specs if s.get("name")]
        if beyaz_liste is None:
            return gecerli

        istenen = list(beyaz_liste)
        mevcut = {s["name"] for s in gecerli}
        bulunmayan = [a for a in istenen if a not in mevcut]
        if bulunmayan:
            self.errors.append(
                f"{name}: 'tools' listesindeki şu araçlar sunucuda yok: "
                + ", ".join(bulunmayan)
            )
        return [s for s in gecerli if s["name"] in istenen]

    def shutdown(self):
        for server in self.servers.values():
            server.stop()
        self.servers = {}
        self.tools = []

    def summary(self):
        if not self.servers and not self.errors:
            return None
        bits = []
        for name, server in self.servers.items():
            n = sum(1 for t in self.tools if t.server is server)
            bits.append(f"{name} ({n} araç)")
        line = "MCP: " + (", ".join(bits) if bits else "sunucu yok")
        if self.errors:
            line += f" — {len(self.errors)} sunucu başlatılamadı"
        return line
