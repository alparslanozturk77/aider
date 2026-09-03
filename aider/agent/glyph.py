"""Terminal Unicode taşımıyorsa ASCII'ye düş.

Kurum sunucularında kodlama her zaman UTF-8 değil ve tek bir karakter satırı
bozuyor: kullanıcı `→ Grep(...)` yerine `?? Grep(...)` görüyor.

Eskiden yalnızca `sys.stdout.encoding`'e bakılıyordu ve bu yetmiyor. Python'un
UTF-8 kipi (`PYTHONUTF8`, `PYTHONIOENCODING`) stdout'u utf-8 gösterebiliyor
ama terminalin kendisi ya da `LANG=C` ile gelen yerel ayar öyle olmayabiliyor;
o durumda `.encode()` sorunsuz geçiyor, ekrana soru işareti düşüyor. Bu yüzden
yerel ayara da bakılıyor.

Sezgi hiçbir zaman kusursuz olmayacak, o yüzden elle anahtar var:
`AIDER_ASCII=1` her şeyi ASCII'ye indirir.
"""

import locale
import os
import sys

# Kullanıcıya görünen metinlerde geçen Unicode karakterlerin ASCII karşılığı.
ASCII_KARSILIK = {
    "→": "->",
    "←": "<-",
    "⏸": "||",
    "⏵": ">",
    "▮": "|",
    "▶": ">",
    "…": "...",
    "—": "-",
    "–": "-",
    "•": "*",
    "✓": "[ok]",
    "✗": "[x]",
    "≈": "~",
    "’": "'",
    "“": '"',
    "”": '"',
}


def _kodlama():
    enc = getattr(sys.stdout, "encoding", None)
    if not enc:
        try:
            enc = locale.getpreferredencoding(False)
        except Exception:
            enc = None
    return enc or "utf-8"


def _yerel_utf8_mu():
    """Yerel ayar açıkça UTF-8 diyor mu?

    Hiçbir değişken tanımlı değilse HAYIR sayılıyor. Eskiden evet sayılıyordu
    ve yanlıştı: `LANG` tanımsız bir ssh oturumu genellikle UTF-8 değildir,
    kullanıcı da ekranda `??` görür. Emin olunmayan durumda sade karakter
    basmak, bozuk karakter basmaktan iyidir.
    """
    for ad in ("LC_ALL", "LC_CTYPE", "LANG"):
        deger = os.environ.get(ad)
        if deger:
            return "utf" in deger.lower().replace("-", "")
    return False


def unicode_destekli():
    """Terminal Unicode basabilir mi?

    Sezgi fontu göremiyor: yerel ayar UTF-8 dese bile terminalin fontunda
    glyph olmayabiliyor ve kullanıcı kutu ya da soru işareti görüyor. Bu yüzden
    iki yönlü elle anahtar var; sezgiye takılan kullanıcı çıkışı bulabilsin.
    """
    if os.environ.get("AIDER_ASCII"):
        return False
    if os.environ.get("AIDER_UNICODE"):
        return True
    try:
        "→…".encode(_kodlama())
    except (UnicodeEncodeError, LookupError):
        return False
    return _yerel_utf8_mu()


# Arayüzün tamamı Türkçe. UTF-8 olmayan bir terminalde bunları soru işaretine
# çevirmek metni okunmaz yapıyor ("sonuç" -> "sonu?"); harf çevirisi hem okunur
# hem alışıldık.
TURKCE_KARSILIK = str.maketrans(
    {
        "ç": "c",
        "Ç": "C",
        "ğ": "g",
        "Ğ": "G",
        "ı": "i",
        "İ": "I",
        "ö": "o",
        "Ö": "O",
        "ş": "s",
        "Ş": "S",
        "ü": "u",
        "Ü": "U",
    }
)


def guvenli(metin):
    """Terminal taşıyorsa metni olduğu gibi, taşımıyorsa ASCII'ye çevirerek döndür."""
    if metin is None:
        return metin
    if unicode_destekli():
        return metin
    for glyph, karsilik in ASCII_KARSILIK.items():
        metin = metin.replace(glyph, karsilik)
    metin = metin.translate(TURKCE_KARSILIK)
    # Listede olmayan bir karakter kalmışsa da ekrana soru işareti düşmesin.
    return metin.encode("ascii", "replace").decode("ascii")
