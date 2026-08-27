#!/bin/sh
# aider-agent kurulum betiği — tek satırda kurulum.
#
#   curl -fsSL https://raw.githubusercontent.com/alparslanozturk77/aider/claude-code-layer/kur.sh | sh
#
# Ne yapar:
#   1. uv yoksa kurar (tek statik ikili, sistem Python'una dokunmaz)
#   2. aider-agent'ı izole bir ortama kurup PATH'e 'aider' komutunu koyar
#   3. ~/.aider altına yapılandırma şablonlarını yerleştirir (varsa dokunmaz)
#
# Python sanal ortamı kurmana ya da yönetmene gerek yok; uv hepsini gizler.

set -eu

REPO_URL="${AIDER_AGENT_REPO:-https://github.com/alparslanozturk77/aider}"
BRANCH="${AIDER_AGENT_BRANCH:-claude-code-layer}"
CONFIG_DIR="$HOME/.aider"

renk() { printf '\033[1m%s\033[0m\n' "$1"; }
bilgi() { printf '  %s\n' "$1"; }
hata() { printf '\033[31mHATA: %s\033[0m\n' "$1" >&2; exit 1; }

renk "aider-agent kuruluyor"
echo

# --- 1. uv ------------------------------------------------------------------

if command -v uv >/dev/null 2>&1; then
    bilgi "uv zaten kurulu: $(uv --version 2>/dev/null || echo bilinmiyor)"
else
    bilgi "uv kuruluyor (tek statik ikili, sistem Python'una dokunmaz)..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 \
            || hata "uv kurulamadı. Elle kur: https://docs.astral.sh/uv/"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 \
            || hata "uv kurulamadı. Elle kur: https://docs.astral.sh/uv/"
    else
        hata "curl ya da wget gerekli"
    fi

    # uv kendini genelde buraya koyar; bu oturum için PATH'e ekle.
    for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
        [ -x "$d/uv" ] && PATH="$d:$PATH"
    done
    export PATH
    command -v uv >/dev/null 2>&1 || hata "uv kuruldu ama PATH'te bulunamadı. Terminali yeniden aç ve tekrar dene."
    bilgi "uv kuruldu"
fi

# --- 2. aider-agent ---------------------------------------------------------

echo
bilgi "aider-agent kuruluyor (bağımlılıklar büyük, birkaç dakika sürebilir)..."

# --force: zaten kuruluysa üzerine yaz, yani bu betik güncelleme için de çalışır.
uv tool install --force "git+${REPO_URL}@${BRANCH}" \
    || hata "kurulum başarısız oldu"

uv tool update-shell >/dev/null 2>&1 || true

# --- 3. Yapılandırma --------------------------------------------------------

echo
if [ -d "$CONFIG_DIR" ]; then
    bilgi "yapılandırma dizini zaten var: $CONFIG_DIR (dokunulmadı)"
else
    mkdir -p "$CONFIG_DIR/skills"
    bilgi "yapılandırma dizini oluşturuldu: $CONFIG_DIR"
fi

echo
renk "Kurulum tamam."
echo
echo "Sırada: modelini tanıt."
echo
echo "  aider --agent          # başlat"
echo "  /model-ekle            # program içinde modeli adım adım tanımla"
echo
echo "'aider' komutu bulunamazsa terminali yeniden aç ya da PATH'e şunu ekle:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
