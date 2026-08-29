#!/bin/sh
# aider-agent çevrimdışı kurulum — ağa çıkmaz.
#
# Kullanım (paketi açtığın dizinde):
#   ./cevrimdisi-kur.sh [hedef-dizin]
#
# Varsayılan hedef: /opt/aider-agent

set -eu

HEDEF="${1:-/opt/aider-agent}"
KAYNAK="$(cd "$(dirname "$0")" && pwd)"

bilgi() { printf '  %s\n' "$1"; }
hata() { printf '\033[31mHATA: %s\033[0m\n' "$1" >&2; exit 1; }

printf '\033[1maider-agent çevrimdışı kurulum\033[0m\n\n'

# --- Python bul -------------------------------------------------------------
# aider >=3.10 istiyor. RHEL 9'un sistem python'ı 3.9 olduğu için orada
# python3.12 paketi gerekir: dnf install python3.12
PY=""
for aday in python3.12 python3.13 python3.11 python3.10 python3; do
    command -v "$aday" >/dev/null 2>&1 || continue
    surum=$("$aday" -c 'import sys; print("%d%02d" % sys.version_info[:2])' 2>/dev/null) || continue
    [ "$surum" -ge 310 ] && [ "$surum" -lt 315 ] || continue
    PY="$aday"
    break
done

[ -n "$PY" ] || hata "Python 3.10-3.14 bulunamadı. RHEL 9'da: dnf install python3.12"
bilgi "Python: $($PY -V) ($(command -v "$PY"))"

[ -d "$KAYNAK/wheels" ] || hata "wheels/ dizini yok — paket eksik açılmış olabilir"
bilgi "Wheel sayısı: $(ls "$KAYNAK/wheels" | wc -l | tr -d ' ')"

# --- Kopyala ----------------------------------------------------------------
if [ "$KAYNAK" != "$HEDEF" ]; then
    mkdir -p "$HEDEF"
    cp -a "$KAYNAK/." "$HEDEF/"
    bilgi "Kopyalandı: $HEDEF"
fi

# --- Sanal ortam ------------------------------------------------------------
bilgi "Sanal ortam kuruluyor (ağa çıkılmıyor)..."
"$PY" -m venv "$HEDEF/.venv"
# DİKKAT: "pip install -e ." kullanılmıyor. Editable kurulum derleme
# bağımlılığı (setuptools>=68) indirmeye çalışıyor ve çevrimdışı ortamda
# "No matching distribution found for setuptools" ile düşüyor — ölçüldü.
# Onun yerine aider-agent'ın kendi wheel'i pakete gömülü geliyor.
"$HEDEF/.venv/bin/python" -m pip install --quiet --no-index \
    --find-links "$HEDEF/wheels" -r "$HEDEF/requirements.txt"
"$HEDEF/.venv/bin/python" -m pip install --quiet --no-index --no-deps \
    --find-links "$HEDEF/wheels" aider-chat

# --- Komut ------------------------------------------------------------------
if [ -w /usr/local/bin ]; then
    cat > /usr/local/bin/aider-agent <<SARMALAYICI
#!/bin/sh
exec "$HEDEF/.venv/bin/aider" "\$@"
SARMALAYICI
    chmod 0755 /usr/local/bin/aider-agent
    bilgi "Komut: /usr/local/bin/aider-agent"
else
    bilgi "Komut: $HEDEF/.venv/bin/aider  (PATH'e eklemek sana kalmış)"
fi

echo
printf '\033[1mKuruldu.\033[0m\n'
bilgi "Beceriler: $HEDEF/aider-skills"
bilgi "Tüm projelerde görünmesi için: ln -s $HEDEF/aider-skills ~/.aider/skills"
bilgi "Modeli tanımla: aider-agent  ->  /model-ekle"
