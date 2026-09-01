"""Oturum kaydı ve kaldığı yerden devam.

Upstream'in `--restore-chat-history`'si bu iş için kullanılamıyor: markdown
sohbet günlüğünün TAMAMINI okuyup ayrıştırıyor (dosya aylar içinde yüz
kilobaytları buluyor) ve araç çağrılarını kaybediyor — `tool_calls` ile
`role="tool"` mesajları markdown'a yazılırken düz metne dönüşüyor, geri
yüklenemiyor. Agent modunda geçmişin yarısı araç trafiği olduğu için bu,
geçmişin yarısını atmak demek.

Burada her oturum kendi JSONL dosyasında, mesajlar API'ye gönderildiği
biçimde duruyor. Satır satır yazılıyor: program çökerse o ana kadarki
geçmiş yine de elde kalıyor.

Dosyalar `.aider/sessions/` altında; `.gitignore`'daki `.aider*` kuralı
sayesinde depoya girmiyorlar. Komut çıktıları içerdikleri için bu bilinçli.
"""

import json
import re
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path(".aider") / "sessions"

# Diskte tutulacak azami oturum sayısı. Eskiler sessizce siliniyor; bir
# oturum dosyası birkaç yüz kilobayt olabiliyor.
MAX_OTURUM = 50

# Geri yüklenen geçmiş için varsayılan karakter tavanı. Gerçek bütçe
# AgentCoder tarafından modelin bağlam penceresine göre daraltılıyor.
DEVAM_BUTCESI = 40_000

BASLIK_UZUNLUK = 70


def _baslik(metin):
    metin = re.sub(r"\s+", " ", (metin or "").strip())
    if len(metin) > BASLIK_UZUNLUK:
        metin = metin[: BASLIK_UZUNLUK - 1] + "…"
    return metin or "(başlıksız)"


class Oturum:
    """Diskteki tek bir oturum dosyası."""

    def __init__(self, path, meta=None, mesaj_sayisi=0, baslik=""):
        self.path = Path(path)
        self.meta = meta or {}
        self.mesaj_sayisi = mesaj_sayisi
        self.baslik = baslik

    @property
    def tarih(self):
        return self.meta.get("baslangic", "")

    def ozet(self):
        tarih = self.tarih.replace("T", " ")[:16]
        return f"{tarih}  {self.mesaj_sayisi:>3} mesaj  {self.baslik}"


class SessionStore:
    """Oturumları yazar, listeler ve geri yükler.

    Yazma hataları oturumu düşürmez: kayıt bir kolaylık, program onsuz da
    çalışmalı. Bir kez yazılamadıysa kayıt sessizce kapatılır ve kullanıcı
    bir kez uyarılır.
    """

    def __init__(self, root, io=None):
        self.root = Path(root)
        self.dizin = self.root / SESSIONS_DIR
        self.io = io
        self.path = None
        self.acik = True

    # -- yazma ---------------------------------------------------------------

    def baslat(self, model_adi=""):
        """Bu çalıştırma için yeni bir oturum dosyası aç."""
        damga = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = self.dizin / f"{damga}.jsonl"
        meta = dict(
            tip="oturum",
            baslangic=datetime.now().isoformat(timespec="seconds"),
            model=model_adi,
            kok=str(self.root),
        )
        if not self._yaz([meta]):
            return None
        self._buda()
        return self.path

    def ekle(self, mesajlar):
        """Turun mesajlarını dosyanın sonuna ekle."""
        if not self.acik or not self.path or not mesajlar:
            return False
        return self._yaz(mesajlar)

    def _yaz(self, satirlar):
        try:
            self.dizin.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                for satir in satirlar:
                    f.write(json.dumps(satir, ensure_ascii=False, default=str) + "\n")
        except (OSError, TypeError, ValueError) as err:
            self.acik = False
            if self.io:
                self.io.tool_warning(f"Oturum kaydı kapatıldı: {err}")
            return False
        return True

    def _buda(self):
        """En eski oturumları sil; dizin sınırsız büyümesin."""
        try:
            dosyalar = sorted(self.dizin.glob("*.jsonl"))
            for yol in dosyalar[:-MAX_OTURUM]:
                yol.unlink()
        except OSError:
            pass

    # -- okuma ---------------------------------------------------------------

    def oturumlar(self):
        """Yeniden eskiye doğru oturum listesi."""
        if not self.dizin.is_dir():
            return []

        out = []
        for yol in sorted(self.dizin.glob("*.jsonl"), reverse=True):
            if yol == self.path:
                continue  # şu an yazdığımız oturum listede görünmesin
            meta, mesajlar = self._oku(yol)
            if not mesajlar:
                continue
            ilk_kullanici = next(
                (m.get("content") for m in mesajlar if m.get("role") == "user"), ""
            )
            out.append(Oturum(yol, meta, len(mesajlar), _baslik(ilk_kullanici)))
        return out

    def son(self):
        oturumlar = self.oturumlar()
        return oturumlar[0] if oturumlar else None

    def _oku(self, yol):
        meta, mesajlar = {}, []
        try:
            with Path(yol).open(encoding="utf-8", errors="replace") as f:
                for satir in f:
                    satir = satir.strip()
                    if not satir:
                        continue
                    try:
                        veri = json.loads(satir)
                    except json.JSONDecodeError:
                        # Yarım yazılmış son satır: dosyanın gerisi geçerli.
                        continue
                    if not isinstance(veri, dict):
                        continue
                    if veri.get("tip") == "oturum":
                        meta = veri
                    elif veri.get("role"):
                        mesajlar.append(veri)
        except OSError:
            return {}, []
        return meta, mesajlar

    def yukle(self, oturum, butce=DEVAM_BUTCESI):
        """Oturumun mesajlarını bütçeye sığacak şekilde geri yükle."""
        _meta, mesajlar = self._oku(getattr(oturum, "path", oturum))
        return budala(mesajlar, butce)


def budala(mesajlar, butce=DEVAM_BUTCESI):
    """Sondan başlayarak bütçeye sığdır, sonra temiz bir sınıra hizala.

    Hizalama şart: `tool_calls` taşıyan bir assistant mesajı ile ona ait
    `role="tool"` yanıtları ayrılırsa endpoint isteği reddediyor ("tool_call
    without response"). Bu yüzden kesme noktasından ileri gidilip ilk
    `user` mesajına hizalanıyor — orası her zaman temiz bir başlangıç.
    """
    if not mesajlar:
        return []

    toplam = 0
    bas = len(mesajlar)
    for i in range(len(mesajlar) - 1, -1, -1):
        boyut = len(json.dumps(mesajlar[i], ensure_ascii=False, default=str))
        if toplam + boyut > butce and bas < len(mesajlar):
            break
        toplam += boyut
        bas = i

    while bas < len(mesajlar) and mesajlar[bas].get("role") != "user":
        bas += 1

    return mesajlar[bas:]
