#!/usr/bin/env bash
# Upstream aider'dan güncelleme al ve fork değişmezlerini doğrula.
#
#   ./scripts/upstream_birlestir.sh              # en son upstream main
#   ./scripts/upstream_birlestir.sh v0.90.0      # belirli bir etiket
#
# Betik merge'i YAPAR ama çakışma çıkarsa çözmez ve commit atmaz; kararı sana
# bırakır. Merge'den sonra fork değişmezlerini ve testleri çalıştırır.

set -uo pipefail

UPSTREAM_URL="https://github.com/Aider-AI/aider.git"
HEDEF="${1:-upstream/main}"
PY="${PYTHON:-.venv/bin/python}"

# Fork'un upstream'e dokunduğu noktalar. Merge sonrası bunlara ayrıca bakılır.
DOKUNULAN=(
    "aider/models.py"
    "aider/coders/__init__.py"
    "aider/args.py"
    "aider/main.py"
    ".gitignore"
)

kalin() { printf '\n\033[1m%s\033[0m\n' "$1"; }
bilgi() { printf '  %s\n' "$1"; }
hata() { printf '\033[31m%s\033[0m\n' "$1" >&2; }

cd "$(git rev-parse --show-toplevel)" || exit 1

# --- ön kontroller ----------------------------------------------------------

if [ -n "$(git status --porcelain)" ]; then
    hata "Çalışma ağacı temiz değil. Önce commit ya da stash yap:"
    git status -s
    exit 1
fi

if [ ! -x "$PY" ]; then
    hata "Python bulunamadı: $PY"
    hata "PYTHON=/yol/python ./scripts/upstream_birlestir.sh ile belirt."
    exit 1
fi

ONCE="$(git rev-parse HEAD)"
DAL="$(git rev-parse --abbrev-ref HEAD)"

# --- upstream'i getir -------------------------------------------------------

kalin "1. Upstream getiriliyor"
if ! git remote get-url upstream >/dev/null 2>&1; then
    bilgi "upstream remote'u ekleniyor"
    git remote add upstream "$UPSTREAM_URL"
fi
# Fork sığ klonlanmış olabilir; merge tabanı bulunabilsin diye derinleştir.
git fetch upstream --tags --unshallow 2>/dev/null || git fetch upstream --tags

if ! git rev-parse --verify "$HEDEF" >/dev/null 2>&1; then
    hata "Böyle bir hedef yok: $HEDEF"
    exit 1
fi

YENI="$(git rev-parse "$HEDEF")"
if git merge-base --is-ancestor "$YENI" HEAD; then
    kalin "Zaten güncel ($HEDEF)."
    exit 0
fi

# --- neyin değiştiğini göster ----------------------------------------------

kalin "2. Dokunduğumuz dosyalarda upstream ne değiştirmiş?"
CAKISMA_RISKI=0
for f in "${DOKUNULAN[@]}"; do
    n=$(git diff --stat HEAD..."$YENI" -- "$f" | tail -1)
    if [ -n "$n" ]; then
        bilgi "DEĞİŞMİŞ  $f"
        CAKISMA_RISKI=1
    else
        bilgi "dokunulmamış  $f"
    fi
done

if [ "$CAKISMA_RISKI" = "1" ]; then
    bilgi ""
    bilgi "Yukarıda 'DEĞİŞMİŞ' görünen dosyalarda çakışma çıkabilir."
fi

# --- merge ------------------------------------------------------------------

kalin "3. Birleştiriliyor: $HEDEF"
if ! git merge --no-edit "$YENI"; then
    hata ""
    hata "Çakışma var. Çöz, sonra:"
    hata "  git add <dosyalar> && git commit"
    hata "  $PY scripts/fork_dogrula.py"
    hata "  $PY -m pytest tests/basic -q"
    hata ""
    hata "Vazgeçmek için: git merge --abort"
    exit 1
fi

# --- doğrulama --------------------------------------------------------------

kalin "4. Fork değişmezleri"
if ! "$PY" scripts/fork_dogrula.py; then
    hata ""
    hata "Merge sonrası fork değişmezleri bozuldu."
    hata "Yukarıdaki her bozuk kontrol hangi dosyaya bakman gerektiğini söylüyor."
    hata ""
    hata "Merge'i geri almak için:"
    hata "  git reset --hard $ONCE"
    exit 1
fi

kalin "5. Testler"
if ! "$PY" -m pytest tests/basic -q --ignore=tests/basic/test_scripting.py; then
    hata ""
    hata "Testler başarısız. Merge commit'i duruyor; düzelt ya da geri al:"
    hata "  git reset --hard $ONCE"
    exit 1
fi

kalin "Birleştirme tamam."
bilgi "dal   : $DAL"
bilgi "önce  : $ONCE"
bilgi "sonra : $(git rev-parse HEAD)"
bilgi ""
bilgi "Değişikliği gözden geçir:  git diff $ONCE..HEAD"
bilgi "Fork'a gönder:             git push fork $DAL"
