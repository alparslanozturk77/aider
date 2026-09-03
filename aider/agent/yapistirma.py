"""Uzun yapıştırmayı prompt'ta yer tutucuya indir.

Terminale 300 satırlık bir log yapıştırıldığında prompt o 300 satırı çiziyor;
ekran kayıyor, kullanıcı ne yazdığını göremiyor ve yanlışlıkla gönderiyor.
Yapıştırılan metin bir yer tutucuya iniyor, gönderirken yerine geri konuyor —
yani modele giden şey değişmiyor, yalnızca ekranda görünen değişiyor.

Yer tutucu istatistik de taşıyor. Dar pencereli bir modelde (kurumdaki vLLM
16k) "kaç token yapıştırdım" sorusunun cevabı göndermeden önce görünmeli;
sonradan bağlam hatası almaktan iyidir.

Aider'ın prompt'u tek satır ve önek solda duruyor, bu yüzden yer tutucu
satırın içine yazılıyor — ayrı bir kutu ya da üst bilgi çubuğu değil. Alt
bilgi çubuğu bu depoda bir kez denenip geri alınmıştı.
"""

from aider.agent.tools import KARAKTER_BASINA_TOKEN

# Bu eşiklerin altındaki yapıştırma zaten prompt'a sığıyor; yer tutucu
# kullanmak kullanıcıyı metninden ayırmaktan başka işe yaramaz.
ESIK_SATIR = 4
ESIK_KARAKTER = 400


def _sayi(n):
    """Türkçe binlik ayracı."""
    return f"{n:,}".replace(",", ".")


def istatistik(metin):
    satir = metin.count("\n") + 1
    token = max(1, round(len(metin) / KARAKTER_BASINA_TOKEN))
    return satir, len(metin), token


class YapistirmaDeposu:
    """Yer tutucu ile gerçek metin arasındaki eşleme.

    Gönderim anında geri açılıyor; açılmayan bir yer tutucu kalırsa (kullanıcı
    satırı elle bozduysa) metin olduğu gibi gider — sessizce kaybolmaz.
    """

    def __init__(self):
        self.parcalar = {}
        self.sayac = 0

    def uzun_mu(self, metin):
        if not metin:
            return False
        return metin.count("\n") + 1 >= ESIK_SATIR or len(metin) >= ESIK_KARAKTER

    def sakla(self, metin):
        self.sayac += 1
        satir, karakter, token = istatistik(metin)
        yer = (
            f"[#{self.sayac} yapıştırıldı: {_sayi(satir)} satır,"
            f" {_sayi(karakter)} karakter, ~{_sayi(token)} token]"
        )
        self.parcalar[yer] = metin
        return yer

    def ac(self, metin):
        if not metin or not self.parcalar:
            return metin
        for yer, gercek in self.parcalar.items():
            metin = metin.replace(yer, gercek)
        return metin

    def temizle(self):
        self.parcalar.clear()
        self.sayac = 0
