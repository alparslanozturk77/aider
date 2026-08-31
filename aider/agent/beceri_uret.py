"""Canlı bir programın kendi yardım çıktısından beceri iskeleti üretir.

Çevrimdışı bir model bilmediği aracın sözdizimini arayamaz; uydurur. `hammer`,
`ipa`, `subscription-manager` gibi araçlarda bu, çalışmayan ya da yanlış şey
yapan komutlar demektir.

Bu modül referansı hafızadan değil aracın kendisinden toplar: `--help` ağacını
gezer, ham çıktıyı becerinin yanına referans dosyası olarak yazar ve `SKILL.md`
iskeletini oluşturur. Gövdeyi model doldurur, ama komut sözdizimini artık
uydurmaz — diskteki gerçek çıktıdan okur.

Program uzak sunucuda da olabilir (`host=`); kurumda `hammer` Satellite'ta,
`ipa` IdM sunucusunda durur, yerel makinede değil.
"""

import os
import re
import shlex
import shutil
import subprocess
from datetime import date
from pathlib import Path

from .skills import SHARED_SKILLS_DIR

# Yardım ağacında kaç alt komuta bakılacak. Sınır var, çünkü `hammer` gibi
# araçlarda 60+ alt komut var ve her biri ayrı bir ssh turu demek.
MAX_ALT_KOMUT = 25

# Tek bir yardım çağrısı için saniye. Yardım çıktısı anında gelir; bu süreyi
# aşan çağrı takılmıştır, beklemenin anlamı yok.
KOMUT_ZAMAN_ASIMI = 15

# Tek bir yardım çıktısından referansa alınacak azami karakter.
MAX_YARDIM_KARAKTER = 6_000

# Referans dosyasının tamamı için bütçe. Ölçüldü: `git` alt komutları
# `--help` çağrısında tam man sayfasını basıyor ve bütçesiz toplama 256 KB'lık
# bir dosya üretiyor — model onu Read ile zaten baştan sona okuyamaz.
TOPLAM_REFERANS_BUTCESI = 100_000

# Çıktının "yardım" sayılması için gereken en az uzunluk. Kısa olanlar
# genelde "unknown option" hata satırıdır.
MIN_YARDIM_KARAKTER = 40

# Kabuk metakarakteri taşıyan program adı ssh üzerinde komut enjeksiyonudur.
PROGRAM_DESENI = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")

YARDIM_BAYRAKLARI = ("--help", "-h", "help")
SURUM_BAYRAKLARI = ("--version", "-V", "version")

# "Commands:", "Subcommands:", "Available Commands:" — alt komut listesinin
# başlığı. Bütün çıktıyı taramak seçenek açıklamalarını komut sanıyor.
_BOLUM_BASLIGI = re.compile(
    r"^.*\b(sub)?commands?\b.*:\s*$|^.*\bkomutlar\b.*:\s*$",
    re.IGNORECASE,
)

# Başlığın altındaki girintili "  ad   açıklama" satırı. Tire ile başlayanlar
# seçenektir, `[a-z]` başlangıcı onları eliyor.
_ALT_KOMUT = re.compile(r"^\s{1,8}([a-z][a-z0-9][a-z0-9_-]*)(?:\s{2,}\S|\s*$)")

# argparse alt komutları tek satırda `{list,show,add}` diye listeler.
_ARGPARSE_KUME = re.compile(r"\{([a-z][a-z0-9_,-]{3,})\}")


class UretimHatasi(Exception):
    """Kullanıcıya gösterilecek, kurtarılamayan üretim hatası."""


def _kirp(metin, sinir):
    if len(metin) <= sinir:
        return metin
    return metin[:sinir] + f"\n... (kırpıldı, tam çıktı {len(metin)} karakter)"


class Calistirici:
    """Komutu yerelde ya da uzak sunucuda çalıştıran ince sarmalayıcı.

    Ssh aracının aksine burada onay sorulmuyor: bu yolu yalnızca kullanıcının
    kendi yazdığı `/beceri-uret` komutu tetikliyor ve çalıştırılan tek şey
    `--help` / `--version`.
    """

    def __init__(self, host=None, timeout=KOMUT_ZAMAN_ASIMI):
        self.host = host
        self.timeout = timeout

    @property
    def nerede(self):
        return self.host or "yerel makine"

    def var_mi(self, program):
        """Program erişilebilir mi?

        Varlık kontrolü çalıştırıcının işi: uzakta `command -v` sorulur,
        yerelde PATH'e bakılır. Testler kendi çalıştırıcısını verdiğinde bu
        da sahtelenebilsin diye modül düzeyinde bir yardımcı değil, metot.
        """
        if self.host:
            rc, _ = self(["command", "-v", program])
            return rc == 0
        return shutil.which(program) is not None

    def __call__(self, argv):
        if self.host:
            komut = " ".join(shlex.quote(a) for a in argv)
            tam = [
                "ssh",
                "-o", "ConnectTimeout=5",
                "-o", "BatchMode=yes",
                self.host,
                komut,
            ]
        else:
            tam = list(argv)

        ortam = dict(os.environ)
        # Pager açılan bir yardım komutu çıktı vermeden bekler; renk kaçış
        # dizileri de referans dosyasını okunmaz hâle getirir.
        ortam.update(PAGER="cat", GIT_PAGER="cat", MANPAGER="cat", NO_COLOR="1", TERM="dumb")

        try:
            proc = subprocess.run(
                tam,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.timeout,
                env=ortam,
            )
        except subprocess.TimeoutExpired:
            return 124, ""
        except OSError as err:
            return 127, str(err)

        # Yardım metnini stdout'a basan da var stderr'e basan da; ayırmıyoruz.
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _ilk_calisan(calistir, argv_onek, bayraklar):
    """Bayrakları sırayla dene, ilk anlamlı çıktıyı döndür.

    Çıkış kodu ölçüt değil: pek çok araç `--help` sonrası 1 ile çıkar. Ölçüt
    çıktının uzunluğu.
    """
    for bayrak in bayraklar:
        _rc, cikti = calistir([*argv_onek, bayrak])
        cikti = cikti.strip()
        if len(cikti) >= MIN_YARDIM_KARAKTER:
            return cikti
    return None


def _surum_bul(calistir, program):
    """Sürüm satırını bul.

    Yardımın aksine sürüm çıktısı KISADIR; uzunluğa bakan ölçüt burada ters
    çalışıyor. Ölçüldü: `git -V` "unknown option: -V" deyip ardından uzun bir
    kullanım metni basıyor ve uzunluk ölçütü onu sürüm sanıyordu. Bu yüzden
    ölçüt üç şart: komut başarılı bitecek, satır kısa olacak, içinde rakam
    geçecek.
    """
    for bayrak in SURUM_BAYRAKLARI:
        rc, cikti = calistir([program, bayrak])
        if rc != 0:
            continue
        satirlar = cikti.strip().splitlines()
        ilk = satirlar[0].strip() if satirlar else ""
        if not ilk or len(ilk) > 120:
            continue
        if not any(k.isdigit() for k in ilk):
            continue
        return ilk
    return None


def alt_komutlari_ayikla(metin, azami=MAX_ALT_KOMUT):
    """Yardım çıktısındaki alt komut adlarını topla."""
    adlar = []
    bolumde = False

    for satir in metin.splitlines():
        if _BOLUM_BASLIGI.match(satir):
            bolumde = True
            continue
        if not bolumde:
            continue
        # Listeyi yalnızca yeni bir bölüm başlığı bitirir, her girintisiz
        # satır değil: git komutlarını "start a working area (...)" gibi
        # girintisiz grup başlıkları altında listeliyor ve her girintisiz
        # satırda durmak o listeyi tamamen kaçırıyordu.
        if satir.strip() and not satir[:1].isspace() and satir.rstrip().endswith(":"):
            bolumde = False
            continue
        m = _ALT_KOMUT.match(satir)
        if m and m.group(1) not in adlar:
            adlar.append(m.group(1))

    for m in _ARGPARSE_KUME.finditer(metin):
        for ad in m.group(1).split(","):
            ad = ad.strip()
            if ad and ad not in adlar:
                adlar.append(ad)

    return adlar[:azami]


def topla(program, host=None, azami_alt=MAX_ALT_KOMUT, calistir=None, bildir=None):
    """Programın yardım ağacını gez ve topladığını sözlük olarak döndür.

    `bildir` her adımda çağrılan geri çağırım; uzun sürebilen bir iş olduğu
    için kullanıcı nerede olduğunu görsün diye var.
    """
    if not PROGRAM_DESENI.match(program or ""):
        raise UretimHatasi(
            f"'{program}' geçerli bir program adı değil. Boşluk, kabuk karakteri ya da "
            "yol ayırıcı içeremez."
        )

    calistir = calistir or Calistirici(host=host)
    bildir = bildir or (lambda _mesaj: None)

    if not calistir.var_mi(program):
        raise UretimHatasi(f"'{program}' {calistir.nerede} üzerinde bulunamadı.")

    surum = _surum_bul(calistir, program)

    bildir(f"{program} --help")
    kok = _ilk_calisan(calistir, [program], YARDIM_BAYRAKLARI)
    if not kok:
        raise UretimHatasi(
            f"'{program}' yardım çıktısı vermedi ({', '.join(YARDIM_BAYRAKLARI)} denendi). "
            "Bu araç için beceriyi elle yazman gerekecek."
        )

    kok = _kirp(kok, MAX_YARDIM_KARAKTER)

    alt_adlar = alt_komutlari_ayikla(kok, azami_alt)
    alt = []
    yardimsiz = []
    atlanan = []
    toplam = len(kok)

    for ad in alt_adlar:
        if toplam >= TOPLAM_REFERANS_BUTCESI:
            atlanan.append(ad)
            continue
        bildir(f"{program} {ad} --help")
        metin = _ilk_calisan(calistir, [program, ad], YARDIM_BAYRAKLARI)
        if not metin:
            yardimsiz.append(ad)
            continue
        metin = _kirp(metin, MAX_YARDIM_KARAKTER)
        alt.append((ad, metin))
        toplam += len(metin)

    return dict(
        program=program,
        nerede=calistir.nerede,
        surum=surum,
        kok=kok,
        alt=alt,
        yardimsiz=yardimsiz,
        atlanan=atlanan,
        tarih=date.today().isoformat(),
    )


def referans_metni(bulgu):
    """Ham yardım ağacını becerinin yanına konacak referans dosyasına çevir."""
    p = bulgu["program"]
    parcalar = [
        f"# `{p}` yardım referansı",
        "",
        f"Toplandı: {bulgu['nerede']} — {bulgu['tarih']}",
        f"Sürüm: {bulgu['surum'] or '(bilinmiyor)'}",
        "",
        "Bu dosya araç çıktısının kendisidir, elle yazılmadı. Komut sözdizimini",
        "buradan al; hafızandan yazma.",
        "",
        f"## {p} --help",
        "",
        "```",
        bulgu["kok"],
        "```",
        "",
    ]

    for ad, metin in bulgu["alt"]:
        parcalar += [f"## {p} {ad} --help", "", "```", metin, "```", ""]

    if bulgu.get("atlanan"):
        parcalar += [
            "## Referans bütçesi dolduğu için taranmayan alt komutlar",
            "",
            ", ".join(bulgu["atlanan"]),
            "",
            f"Gerekirse sunucuda tek tek `{p} <alt komut> --help` ile bak.",
            "",
        ]

    if bulgu["yardimsiz"]:
        parcalar += [
            "## Yardım çıktısı alınamayan alt komutlar",
            "",
            ", ".join(bulgu["yardimsiz"]),
            "",
            "Bunları kullanmadan önce sunucuda elle `--help` ile teyit et.",
            "",
        ]

    return "\n".join(parcalar)


def iskelet_metni(ad, bulgu, referans_yolu):
    """Model tarafından doldurulacak SKILL.md iskeleti."""
    p = bulgu["program"]
    alt_liste = ", ".join(a for a, _ in bulgu["alt"]) or "(alt komut bulunamadı)"

    return f"""---
name: {ad}
description: DOLDUR — bu beceri NE ZAMAN kullanılacak? `{p}` aracıyla yapılan
  işleri ve kullanıcının yazacağı tetikleyici kelimeleri say.
---

Doğrulandı: {bulgu['surum'] or p}, {bulgu['nerede']} — {bulgu['tarih']}

## Komut referansı

Bu aracın komut sözdizimini **ezberden yazma**. Tam yardım ağacı diskte:

    {referans_yolu}

İhtiyacın olduğunda Read ile oku. Aşağıya yalnızca sık kullanılan komutları
ve **çıktının nasıl okunacağını** yaz; komut listesinin tamamı referansta.

Bulunan alt komutlar: {alt_liste}

## 1. DOLDUR — ilk adım

Kullanıcı bu aracı ilgilendiren bir şey istediğinde önce ne yapılacak?
Somut komut yaz, "dikkatli ol" gibi ifade değil.

## 2. DOLDUR — çıktı nasıl okunur

Asıl değer komut listesinde değil, çıktının yorumunda: hangi alan hangi
sorunu gösterir, eşik nedir, ne zaman alarm verilir.

## DOLDUR — yan etkili komutlar

Hangi komutlar bir şey değiştirir? Onay almadan çalıştırılmayacak olanları
buraya listele.

## Raporlama

Sonuç kullanıcıya nasıl sunulacak?
"""


def uret(kok, program, host=None, ad=None, bildir=None, calistir=None):
    """Referansı ve iskeleti diske yaz; (beceri_adi, yazilan_yollar) döndür.

    Var olan bir `SKILL.md`'nin üstüne yazılmaz: emek verilmiş bir beceriyi
    yeniden tarama sessizce silerdi. Referans dosyası ise tazelenir — zaten
    aracın kendi çıktısı.
    """
    bulgu = topla(program, host=host, calistir=calistir, bildir=bildir)

    ad = ad or program.replace("_", "-").replace(".", "-")
    beceri_dizini = Path(kok) / SHARED_SKILLS_DIR / ad
    referans_dizini = beceri_dizini / "referans"
    referans_dizini.mkdir(parents=True, exist_ok=True)

    referans = referans_dizini / "yardim.md"
    referans.write_text(referans_metni(bulgu), encoding="utf-8")
    yazilan = [referans]

    skill_md = beceri_dizini / "SKILL.md"
    if not skill_md.exists():
        goreli = referans.relative_to(Path(kok))
        skill_md.write_text(iskelet_metni(ad, bulgu, goreli), encoding="utf-8")
        yazilan.append(skill_md)

    return ad, bulgu, yazilan
