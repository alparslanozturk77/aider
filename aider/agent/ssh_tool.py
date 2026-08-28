"""Uzak sunucuda komut çalıştırma aracı.

Ayrı bir araç olmasının sebebi: model `ssh` komutunu Bash ile kendisi kurunca
sunucu adını uyduruyor. Gözlendi — kullanıcı "skyup" dedi, model
`ssh skyup@kurum.local` üretti; öyle bir adres yok, `skyup` kullanıcının
`~/.ssh/config` dosyasındaki bir takma ad.

Bu araç adı uydurmayı **yapısal olarak** engelliyor: sunucu adı
`~/.ssh/config` içinde tanımlı değilse komut hiç çalıştırılmıyor ve modele
tanımlı adların listesi veriliyor.
"""

import re
import subprocess
from pathlib import Path

from .registry import ToolError
from .tools import Tool, _truncate

SSH_CONFIG = Path.home() / ".ssh" / "config"

# Uzak komutlar takılmasın: ad çözülmüyorsa ya da anahtar yoksa hemen dönsün.
CONNECT_TIMEOUT = 5
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600

_HOST_LINE = re.compile(r"^\s*Host\s+(.+?)\s*$", re.IGNORECASE)


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

        tanimli = known_hosts()

        # Modelin en sık yaptığı hata: takma ada user@ ya da alan adı eklemek.
        if "@" in host or "." in host:
            sade = host.split("@")[-1].split(".")[0]
            ipucu = f" '{sade}' demek istemiş olabilirsin." if sade in tanimli else ""
            raise ToolError(
                f"'{host}' bir takma ad değil. Kullanıcının verdiği adı olduğu gibi "
                f"kullan; user@ ya da alan adı ekleme.{ipucu} "
                f"Tanımlı adlar: {', '.join(tanimli) or '(yok)'}"
            )

        if host not in tanimli:
            raise ToolError(
                f"'{host}' ~/.ssh/config içinde tanımlı değil, bağlanmayı denemiyorum. "
                f"Tanımlı adlar: {', '.join(tanimli) or '(yok)'}. "
                "Kullanıcı başka bir sunucu kastediyorsa ona sor."
            )

        timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))

        if not ctx.confirm(
            self.name,
            f"{host}: {command}",
            "Uzak sunucuda komut çalıştır?",
            args=dict(host=host, command=command),
        ):
            return "Kullanıcı bu uzak komutu reddetti."

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
        return _truncate(cikti)
