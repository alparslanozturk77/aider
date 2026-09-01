"""Bağlamı özetleyerek sıkıştırma — Claude Code'un `/compact`'ının karşılığı.

Upstream'in `ChatSummary`'si bu iş için kullanılamıyor: mesajları user /
assistant çiftleri sanıyor. Agent modunda geçmişin yarısı `tool_calls`
taşıyan assistant mesajları ve onların `role="tool"` yanıtları. ChatSummary
kesme noktasını gelişigüzel seçtiği için ortada kalan bir `tool_calls`
endpoint tarafından reddediliyor ("tool_call without response") — oturum
budamasının (`oturum.budala`) düştüğü tuzağın aynısı. Burada da kesme
noktası her zaman bir `user` mesajına hizalanıyor.

Veri kaybı yok: özet yalnızca **modele giden** bağlamı değiştirir. Oturumun
tam kaydı `.aider/sessions/` altındaki JSONL'de satır satır durmaya devam
eder, `--continue` onu okur.
"""

# Aynen korunacak son kullanıcı turu sayısı. İkiden azı, "az önce ne
# yapmıştık"ı özete bırakıyor; modelin son adımları ham görmesi gerekiyor.
KORUNAN_TUR = 2

# Döküme giren tek bir araç sonucunun karakter tavanı. Özetlenecek metin
# zaten uzun; ham `rpm -qa` çıktısını modele ikinci kez göndermenin anlamı yok.
ARAC_CIKTI_TAVANI = 600

# Özetlenecek dökümün tamamının tavanı.
DOKUM_TAVANI = 60_000

# Araç çağrısı argümanlarının döküme giren kısmı.
ARGUMAN_TAVANI = 200

# Özet mesajının başlığı. Bir sonraki sıkıştırmada önceki özeti tanımak için
# de kullanılıyor — önceki özet döküme her zaman tam girer, yoksa arka arkaya
# sıkıştırmalarda en eski bilgi sessizce eriyor.
OZET_ONEKI = "Önceki konuşmanın özeti"

SISTEM_ISTEMI = (
    "Sen bir sistem yöneticisiyle çalışan yazılım ajanısın. Aşağıda bir"
    " oturumun dökümü var. Konuşma devam edecek; senin işin, devam eden"
    " oturumun bağlamını korumak."
)

KULLANICI_ISTEMI = """Aşağıdaki oturum dökümünü özetle.

Bu özet, konuşmanın ham geçmişinin YERİNE geçecek. Özette olmayan hiçbir şeyi
sonradan hatırlayamayacaksın, o yüzden şunları kaybetme:

- Kullanıcının ne istediği ve hangi kararları verdiği
- Çalıştırılan komutlar ve sonuçları
- Dosya yolları, sunucu adları, paket ve sürüm numaraları
- Karşılaşılan hatalar ve çözülüp çözülmediği
- Yarım kalan işler ve sıradaki adım

Kurallar: Türkçe yaz. Başlıklarla, madde madde. Yorum ve övgü ekleme; olan
biteni yaz. Dosya yolu, komut ve sunucu adlarını AYNEN yaz, kısaltma.

--- DÖKÜM BAŞI ---
{dokum}
--- DÖKÜM SONU ---"""


def toplam_karakter(mesajlar):
    """Mesaj listesinin kabaca kapladığı yer."""
    return sum(len(str(m.get("content") or "")) for m in mesajlar)


def _kullanici_indeksleri(mesajlar):
    return [i for i, m in enumerate(mesajlar) if m.get("role") == "user"]


def kesme_noktasi(mesajlar, korunan_tur=KORUNAN_TUR):
    """`mesajlar[:i]` özetlenir, `mesajlar[i:]` aynen kalır.

    Sıfır dönerse özetlenecek kadar geçmiş yok demektir. Dönen indeks her
    zaman bir `user` mesajını gösterir: `tool_calls` taşıyan bir assistant
    mesajını kendi `tool` yanıtlarından ayırmak isteği geçersiz kılıyor.
    """
    if korunan_tur < 1:
        korunan_tur = 1
    kullanicilar = _kullanici_indeksleri(mesajlar)
    if len(kullanicilar) <= korunan_tur:
        return 0
    return kullanicilar[-korunan_tur]


def _arac_adlari(msg):
    for call in msg.get("tool_calls") or []:
        fn = call.get("function") or {}
        ad = fn.get("name") or "?"
        args = str(fn.get("arguments") or "")
        if len(args) > ARGUMAN_TAVANI:
            args = args[:ARGUMAN_TAVANI] + "…"
        yield f"{ad}({args})"


def _satir(msg, arac_tavani):
    rol = msg.get("role")
    icerik = str(msg.get("content") or "").strip()

    if rol == "user":
        return f"KULLANICI: {icerik}" if icerik else None

    if rol == "assistant":
        parcalar = []
        if icerik:
            parcalar.append(f"ASİSTAN: {icerik}")
        for cagri in _arac_adlari(msg):
            parcalar.append(f"ASİSTAN araç çağırdı: {cagri}")
        return "\n".join(parcalar) or None

    if rol == "tool":
        if len(icerik) > arac_tavani:
            icerik = icerik[:arac_tavani] + f"… (+{len(icerik) - arac_tavani} karakter)"
        return f"ARAÇ SONUCU [{msg.get('name') or '?'}]: {icerik}"

    return None


def _onceki_ozet(mesajlar):
    """Varsa bir önceki sıkıştırmanın özeti — döküme her zaman tam girer."""
    for msg in reversed(mesajlar):
        if msg.get("role") != "assistant":
            continue
        icerik = str(msg.get("content") or "")
        if icerik.startswith(OZET_ONEKI):
            return icerik
    return None


def dokum(mesajlar, arac_tavani=ARAC_CIKTI_TAVANI, tavan=DOKUM_TAVANI):
    """Özetlenecek mesajları düz metne çevir.

    Bütçe aşılırsa baştan kırpılır, sondan değil: yaklaşan turlara en yakın
    olan kısım en değerlisi. Önceki özet bu kırpmadan muaf.
    """
    ozet = _onceki_ozet(mesajlar)

    satirlar = []
    for msg in mesajlar:
        if ozet and str(msg.get("content") or "") == ozet:
            continue
        satir = _satir(msg, arac_tavani)
        if satir:
            satirlar.append(satir)

    bas = ozet + "\n\n" if ozet else ""
    kalan_tavan = max(1_000, tavan - len(bas))

    govde = "\n\n".join(satirlar)
    if len(govde) > kalan_tavan:
        govde = "(dökümün başı kısaltıldı)\n\n" + govde[-kalan_tavan:]

    return bas + govde


def istem(dokum_metni):
    """Özetleyici çağrısının mesajları."""
    return [
        dict(role="system", content=SISTEM_ISTEMI),
        dict(role="user", content=KULLANICI_ISTEMI.format(dokum=dokum_metni)),
    ]


def ozet_mesaji(metin):
    """Özeti geçmişe koyulacak mesaja çevir.

    Rol `assistant`: özetten hemen sonra korunan blok bir `user` mesajıyla
    başlıyor ve arka arkaya iki `user` mesajı bazı sohbet şablonlarını
    (vLLM/Qwen) bozuyor.
    """
    return dict(role="assistant", content=f"{OZET_ONEKI}\n\n{metin.strip()}")


def uygula(mesajlar, metin, kes):
    """Özetlenmiş yeni geçmiş: [özet] + aynen korunan son turlar."""
    return [ozet_mesaji(metin)] + list(mesajlar[kes:])
