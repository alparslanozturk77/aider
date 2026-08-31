"""Uzak sunucuda komut çalıştırma aracı.

Ayrı bir araç olmasının sebebi: model `ssh` komutunu Bash ile kendisi kurunca
sunucu adını uyduruyor. Gözlendi — kullanıcı "skyup" dedi, model
`ssh skyup@kurum.local` üretti; öyle bir adres yok, `skyup` kullanıcının
`~/.ssh/config` dosyasındaki bir takma ad.

Bu araç adı uydurmayı engelliyor ama körü körüne değil. Sunucu adı üç
kaynakta aranıyor:

  1. `~/.ssh/config`      takma adlar
  2. `~/.ssh/known_hosts` daha önce bağlanılmış makineler
  3. ansible envanterleri proje altındaki `hosts*.ini` / `*.yml`

Hiçbirinde yoksa komut **reddedilmiyor, kullanıcıya soruluyor**: public-key
kimlik doğrulaması kurulmuş ve DNS'te çözülen bir sunucu (`ssh srvsatellite
"komut"`) hiçbir yapılandırma dosyasında görünmeyebilir. Ölçüldü — eski
davranış bu tür sunucuları tümden engelliyordu. Onaylanan ad oturum boyunca
hatırlanır, her komutta tekrar sorulmaz.
"""

import re
import subprocess
from pathlib import Path

from .registry import ToolError
from .tools import Tool, _truncate, cikti_siniri

SSH_CONFIG = Path.home() / ".ssh" / "config"

# Uzak komutlar takılmasın: ad çözülmüyorsa ya da anahtar yoksa hemen dönsün.
CONNECT_TIMEOUT = 5
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600

_HOST_LINE = re.compile(r"^\s*Host\s+(.+?)\s*$", re.IGNORECASE)

KNOWN_HOSTS = Path.home() / ".ssh" / "known_hosts"

# Ansible envanteri aranan dosya adları. Proje kökü ve bir alt dizin taranır;
# daha derine inmek büyük depolarda açılışı yavaşlatıyor.
ENVANTER_DESENLERI = ("hosts", "hosts*.ini", "hosts*.yml", "hosts*.yaml", "inventory*")

# Tek bir taramada okunacak azami envanter dosyası.
MAX_ENVANTER_DOSYA = 20


def _joker_mi(ad):
    return any(k in ad for k in "*?!")


def known_hosts_dosyasi(path=None):
    """~/.ssh/known_hosts içindeki makine adları.

    Karma (hashed) girdiler `|1|` ile başlar ve geri çözülemez; atlanır.
    """
    path = Path(path) if path else KNOWN_HOSTS
    if not path.is_file():
        return []

    adlar = []
    try:
        for satir in path.read_text(encoding="utf-8", errors="replace").splitlines():
            satir = satir.strip()
            if not satir or satir.startswith(("#", "|", "@")):
                continue
            alan = satir.split()[0]
            for ad in alan.split(","):
                # "[sunucu]:2222" biçimi standart olmayan port demek.
                ad = ad.strip().lstrip("[").split("]")[0]
                if ad and not _joker_mi(ad) and ad not in adlar:
                    adlar.append(ad)
    except OSError:
        return []
    return adlar


def _ini_envanter_hostlari(metin):
    adlar = []
    for satir in metin.splitlines():
        satir = satir.strip()
        if not satir or satir.startswith(("#", ";", "[")):
            continue
        ilk = satir.split()[0]
        # "[web:vars]" bloğundaki "ansible_user=root" gibi satırlar host değil.
        if "=" in ilk:
            continue
        if ilk not in adlar:
            adlar.append(ilk)
    return adlar


def _yaml_envanter_hostlari(metin):
    """YAML envanterindeki `hosts:` haritalarının anahtarlarını topla."""
    try:
        import yaml

        veri = yaml.safe_load(metin)
    except Exception:
        return []

    adlar = []

    def gez(dugum):
        if isinstance(dugum, dict):
            for anahtar, deger in dugum.items():
                if anahtar == "hosts" and isinstance(deger, dict):
                    adlar.extend(a for a in deger if isinstance(a, str))
                elif anahtar == "hosts" and isinstance(deger, list):
                    adlar.extend(a for a in deger if isinstance(a, str))
                else:
                    gez(deger)
        elif isinstance(dugum, list):
            for oge in dugum:
                gez(oge)

    gez(veri)
    return [a for a in dict.fromkeys(adlar) if not _joker_mi(a)]


def envanter_hostlari(root):
    """Proje altındaki ansible envanterlerinde geçen sunucu adları.

    Kullanıcının işi ansible ağırlıklı; envanterde duran bir makineyi
    "tanımlı değil" diye reddetmek yolun ortasına duvar örmek olurdu.
    """
    if not root:
        return []
    kok = Path(root)
    if not kok.is_dir():
        return []

    dosyalar = []
    for desen in ENVANTER_DESENLERI:
        dosyalar += list(kok.glob(desen)) + list(kok.glob(f"*/{desen}"))

    adlar = []
    for yol in dosyalar[:MAX_ENVANTER_DOSYA]:
        if not yol.is_file():
            continue
        try:
            metin = yol.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if yol.suffix in (".yml", ".yaml"):
            bulunan = _yaml_envanter_hostlari(metin)
        else:
            bulunan = _ini_envanter_hostlari(metin)
        for ad in bulunan:
            if ad not in adlar:
                adlar.append(ad)
    return adlar


def bilinen_sunucular(root=None):
    """Üç kaynaktan derlenmiş sunucu adı -> kaynak eşlemesi."""
    kaynaklar = (
        ("~/.ssh/config", known_hosts()),
        ("~/.ssh/known_hosts", known_hosts_dosyasi()),
        ("ansible envanteri", envanter_hostlari(root)),
    )
    out = {}
    for kaynak, adlar in kaynaklar:
        for ad in adlar:
            out.setdefault(ad, kaynak)
    return out


def known_hosts(config_path=None):
    """~/.ssh/config içindeki takma adları oku.

    Joker içerenler (`Host *`) atlanır: onlar bağlanılacak bir sunucu değil,
    diğer girdilere uygulanan varsayılanlardır.
    """
    path = Path(config_path) if config_path else SSH_CONFIG
    if not path.is_file():
        return []

    adlar = []
    try:
        for satir in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _HOST_LINE.match(satir)
            if not m:
                continue
            for ad in m.group(1).split():
                if "*" in ad or "?" in ad or "!" in ad:
                    continue
                if ad not in adlar:
                    adlar.append(ad)
    except OSError:
        return []
    return adlar


class SshTool(Tool):
    name = "Ssh"
    # Açıklama kasıtlı olarak kısa ve örnekli: uzun prose, zayıf modellerde
    # şemayı gölgeliyor ve model zorunlu argümanları boş bırakıyor.
    # Gözlendi — gemma4:e4b bu aracı "Ssh()" diye argümansız çağırdı.
    description = (
        "Uzak sunucuda komut çalıştırır. Örnek: host=\"skyup\", command=\"df -h\". "
        "host, kullanıcının söylediği adın aynısı olmalı — user@ ya da alan adı ekleme."
    )
    mutating = True
    parameters = {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "Sunucu takma adı. Örnek: skyup",
                "examples": ["skyup", "fedora"],
            },
            "command": {
                "type": "string",
                "description": "Uzakta çalıştırılacak komut. Örnek: df -h",
                "examples": ["df -h", "systemctl is-active nginx"],
            },
            "timeout": {
                "type": "integer",
                "description": f"Saniye (varsayılan {DEFAULT_TIMEOUT}, en fazla {MAX_TIMEOUT})",
            },
        },
        "required": ["host", "command"],
    }

    def run(self, ctx, host, command, timeout=DEFAULT_TIMEOUT):
        host = (host or "").strip()
        command = (command or "").strip()

        if not host:
            raise ToolError("host zorunlu")
        if not command:
            raise ToolError("command zorunlu")

        bilinen = bilinen_sunucular(getattr(ctx, "root", None))
        adlar = ", ".join(sorted(bilinen)) or "(yok)"

        # Modelin en sık yaptığı hata: takma ada user@ ya da alan adı eklemek.
        if "@" in host:
            sade = host.split("@")[-1].split(".")[0]
            ipucu = f" '{sade}' demek istemiş olabilirsin." if sade in bilinen else ""
            raise ToolError(
                f"'{host}' bir sunucu adı değil, kullanıcı adı eklenmiş. Kullanıcının "
                f"verdiği adı olduğu gibi kullan.{ipucu} Bilinen adlar: {adlar}"
            )

        # Alan adı eklenmiş ad, yalnızca gerçekten bilinen bir ad değilse
        # reddedilir: known_hosts pekâlâ FQDN tutuyor olabilir.
        if "." in host and host not in bilinen:
            sade = host.split(".")[0]
            ipucu = f" '{sade}' demek istemiş olabilirsin." if sade in bilinen else ""
            raise ToolError(
                f"'{host}' bilinen bir sunucu değil ve alan adı eklenmiş görünüyor. "
                f"Kullanıcının verdiği adı olduğu gibi kullan; alan adı ekleme.{ipucu} "
                f"Bilinen adlar: {adlar}"
            )

        timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))

        if not ctx.confirm(
            self.name,
            f"{host}: {command}",
            "Uzak sunucuda komut çalıştır?",
            args=dict(host=host, command=command),
        ):
            return "Kullanıcı bu uzak komutu reddetti."

        # Hiçbir kaynakta yoksa reddetmiyoruz, soruyoruz: public-key ile
        # çalışan ve DNS'te çözülen bir sunucu (srvsatellite gibi) hiçbir
        # yapılandırma dosyasında görünmeyebilir. Soru ctx.confirm'den AYRI
        # ve doğrudan io üzerinden soruluyor; oto modda bile sorulsun diye.
        if host not in bilinen and host not in ctx.onaylanan_sunucular:
            if not ctx.io.confirm_ask(
                f"'{host}' bilinen sunucular arasında yok. Yine de bağlanılsın mı?",
                subject=f"{host}: {command}",
            ):
                return (
                    f"Kullanıcı '{host}' sunucusuna bağlanmayı onaylamadı. "
                    f"Bilinen adlar: {adlar}. Doğru adı kullanıcıya sor."
                )
            ctx.onaylanan_sunucular.add(host)

        argv = [
            "ssh",
            "-o", f"ConnectTimeout={CONNECT_TIMEOUT}",
            # Parola istemi agent'ın terminali olmadığı için cevaplanamaz;
            # anahtar yoksa takılmak yerine hemen hata versin.
            "-o", "BatchMode=yes",
            host,
            command,
        ]

        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, errors="replace", timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return f"'{host}' {timeout} saniyede yanıt vermedi: {command}"
        except OSError as err:
            raise ToolError(f"ssh başlatılamadı: {err}")

        cikti = ((proc.stdout or "") + (proc.stderr or "")).strip() or "(çıktı yok)"

        if proc.returncode == 255:
            # 255 ssh'ın kendi hata kodu: bağlantı kurulamadı.
            return f"'{host}' sunucusuna bağlanılamadı:\n{cikti}"
        if proc.returncode != 0:
            cikti += f"\n[uzak komut çıkış kodu {proc.returncode}]"

        # Komutu tekrar yazdırmıyoruz: hem araç çağrısı satırı hem onay istemi
        # zaten gösteriyor, üç kez tekrarlanıyordu.
        return _truncate(cikti, cikti_siniri(ctx))
