"""MCP (Model Context Protocol) istemcisi.

Harici MCP sunucularını stdio üzerinden başlatır, sundukları araçları keşfeder
ve agent'ın araç kayıt defterine ekler. Sunucu araçları
`mcp__<sunucu>__<araç>` adıyla görünür, böylece yerleşik araçlarla çakışmaz.

Bağımlılık eklememek için resmi MCP SDK'sı yerine satır bazlı JSON-RPC 2.0
konuşan küçük ve senkron bir istemci kullanılıyor; aider'ın gövdesi senkron
olduğu için async bir istemci köprülemek gereksiz karmaşıklık getirirdi.

Yapılandırma, Claude Code ile aynı biçimde `.mcp.json` dosyasından okunur:

    {
      "mcpServers": {
        "postgres": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-postgres", "postgres://..."],
          "env": {"PGPASSWORD": "..."}
        }
      }
    }
"""

import atexit
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from .registry import ToolError
from .tools import Tool, _truncate

PROTOCOL_VERSION = "2024-11-05"

# Sunucu başlatma ve tek bir isteğin yanıtı için tavan süreler.
STARTUP_TIMEOUT = 30
REQUEST_TIMEOUT = 120

CONFIG_NAMES = (".mcp.json", ".aider/mcp.json")


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

    # -- süreç yaşam döngüsü -------------------------------------------------

    def start(self):
        """Sunucuyu başlat, el sıkış ve araçlarını keşfet."""
        full_env = os.environ.copy()
        full_env.update(self.env)

        try:
            self.proc = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=full_env,
                cwd=self.cwd,
                text=True,
                bufsize=1,
            )
        except (OSError, ValueError) as err:
            raise MCPError(f"'{self.command}' başlatılamadı: {err}")

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

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
        self.tools = result.get("tools", []) or []
        return self.tools

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
        result = self._request("tools/call", {"name": tool_name, "arguments": arguments})

        # MCP yanıtı bir içerik parçaları listesidir; metin olanları birleştir.
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
        if not isinstance(cfg, dict) or not cfg.get("command"):
            raise MCPError(f"{path}: '{name}' sunucusunda 'command' eksik")
        out[name] = cfg
    return out


class MCPManager:
    """Yapılandırılmış tüm MCP sunucularını yönetir."""

    def __init__(self, io, project_root):
        self.io = io
        self.project_root = project_root
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
            server = MCPServer(
                name=name,
                command=cfg["command"],
                args=cfg.get("args"),
                env=cfg.get("env"),
                cwd=cfg.get("cwd") or self.project_root,
            )
            try:
                specs = server.start()
            except MCPError as err:
                server.stop()
                self.errors.append(f"{name}: {err}")
                continue

            self.servers[name] = server
            for spec in specs:
                if not spec.get("name"):
                    continue
                self.tools.append(MCPTool(server, spec))

        return self.tools

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
