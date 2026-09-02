"""Program içinden adım adım model tanımlama.

/model-ekle komutunun arkasındaki mantık. Tek soru sorar — endpoint adresi —,
sunulan modelleri /v1/models üzerinden listeleyip seçtirir, bağlam penceresini
yanıttan okur, fonksiyon çağırma desteğini küçük bir istekle dener ve aider'ın
yapılandırmasını yazar.

Eskiden ilk soru "endpoint tipi" idi (kurum / ollama / yerel). Üçü de aynı
litellm sağlayıcısını (`openai/`) kullandığı için soru yalnızca hangi
varsayılan adresin doldurulacağını seçiyordu; kullanıcı zaten adresi
yazacaksa sorunun bir karşılığı yok. Kaldırıldı.

Yazılan dosyalar:

    ~/.aider.conf.yml               model adı, endpoint adresi, anahtar
    ~/.aider/model.settings.yml     edit_format, repo-map, sıcaklık
    ~/.aider/model.metadata.json    bağlam penceresi

Üç dosya aider'ın kendi tasarımı, fork'un icadı değil: biri CLI varsayılanları,
biri litellm model ayarları, biri litellm maliyet/pencere verisi. Tek dosyada
birleştirilemiyorlar ama tek dizinde toplanabiliyorlar — conf dosyası
`model-settings-file` ve `model-metadata-file` ile ikisini gösteriyor.
`~/.aider.conf.yml` yerinde kalmak zorunda: aider'ın kendiliğinden bulduğu
giriş noktası orası.

Ev dizinine yazılır, böylece tanım tüm projelerde geçerli olur. Anahtar içeren
dosya 0600 izniyle oluşturulur.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import yaml

# Endpoint sorgularının tavanı. Kurum ağında ulaşılamayan bir adres kurulumu
# askıda bırakmamalı; liste alınamazsa akış elle girişe düşüyor.
HTTP_ZAMAN_ASIMI = 10

# /v1/models yanıtında bağlam penceresinin görülebildiği alanlar. vLLM
# "max_model_len" veriyor, kimi ağ geçitleri "context_length".
PENCERE_ALANLARI = ("max_model_len", "context_length", "max_input_tokens", "context_window")

DEFAULT_CONTEXT = 262144
DEFAULT_MAX_OUTPUT = 8192


class ModelSetupCancelled(Exception):
    """Kullanıcı kurulumu yarıda bıraktı."""


def _istek(url, api_key, veri=None, timeout=HTTP_ZAMAN_ASIMI):
    """Endpoint'e tek bir JSON isteği at. Başarısızlıkta None döner.

    Hiçbir hata yükseltilmiyor: model tanımlama, endpoint sorgulanamadığı
    için düşmemeli — elle girişe düşmek her zaman mümkün.
    """
    basliklar = {"Content-Type": "application/json"}
    if api_key:
        basliklar["Authorization"] = f"Bearer {api_key}"

    govde = json.dumps(veri).encode("utf-8") if veri is not None else None
    istek = urllib.request.Request(url, data=govde, headers=basliklar)
    try:
        with urllib.request.urlopen(istek, timeout=timeout) as yanit:
            return json.loads(yanit.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def taban_adresi(url):
    """Kullanıcının yapıştırdığı adresi /v1 ile biten bir tabana çevir.

    Kullanıcı tarayıcıdan ya da bir belgeden ne yapıştırırsa yapıştırsın
    çalışsın: şema eksik olabilir, sonda /models ya da /chat/completions
    kalmış olabilir, /v1 hiç yazılmamış olabilir.
    """
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    if url.endswith("/v1"):
        return url
    if "/v1/" in url:
        return url[: url.index("/v1/") + 3]
    return url + "/v1"


def modelleri_getir(api_base, api_key):
    """Endpoint'in sunduğu model kimlikleri. Alınamazsa boş liste."""
    if not api_base:
        return []
    veri = _istek(api_base.rstrip("/") + "/models", api_key)
    if not isinstance(veri, dict):
        return []
    kayitlar = veri.get("data")
    if not isinstance(kayitlar, list):
        return []
    return [k for k in kayitlar if isinstance(k, dict) and k.get("id")]


def _pencere_bul(kayit):
    """Model kaydından bağlam penceresini oku."""
    for alan in PENCERE_ALANLARI:
        deger = kayit.get(alan)
        if isinstance(deger, int) and deger > 0:
            return deger
    return None


def arac_destegi_dene(api_base, api_key, model_id):
    """Model gerçekten fonksiyon çağırabiliyor mu, küçük bir istekle dene.

    Agent modu buna bağlı. Desteklemeyen bir model sessizce tanımlanırsa
    belirtisi "model hiç araç çağırmıyor" oluyor ve sebebi görünmüyor.

    (destekliyor_mu, açıklama) döndürür; deneme yapılamadıysa (None, sebep).
    """
    if not api_base:
        return None, "endpoint adresi yok"

    istek = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Ankara'da hava nasıl?"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "hava_durumu",
                    "description": "Bir şehrin hava durumunu döndürür",
                    "parameters": {
                        "type": "object",
                        "properties": {"sehir": {"type": "string"}},
                        "required": ["sehir"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "max_tokens": 64,
    }

    yanit = _istek(api_base.rstrip("/") + "/chat/completions", api_key, istek)
    if yanit is None:
        return None, "endpoint yanıt vermedi"
    if not isinstance(yanit, dict) or not yanit.get("choices"):
        return None, "beklenmeyen yanıt biçimi"

    mesaj = (yanit["choices"][0] or {}).get("message") or {}
    if mesaj.get("tool_calls"):
        return True, "araç çağrısı döndü"
    return False, "model araç yerine düz metinle yanıt verdi"


def _read_yaml(path):
    if not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _read_json(path):
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_private(path, text):
    """Gizli bilgi içerebilecek dosyayı yalnızca sahibinin okuyabileceği izinle yaz."""
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _ask_choice(io, question, options):
    """options: (anahtar, açıklama) listesi. Seçilen anahtarı döndürür."""
    io.tool_output()
    for i, (key, desc) in enumerate(options, 1):
        io.tool_output(f"  {i}) {desc}")
    io.tool_output()

    while True:
        raw = io.prompt_ask(f"{question} [1-{len(options)}]", default="1").strip()
        if not raw:
            raw = "1"
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        io.tool_error(f"1 ile {len(options)} arasında bir sayı gir.")


def _ask_int(io, question, default):
    while True:
        raw = io.prompt_ask(f"{question}", default=str(default)).strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            io.tool_error("Bir sayı gir.")
            continue
        if value <= 0:
            io.tool_error("Sıfırdan büyük olmalı.")
            continue
        return value


def _model_sec(io, api_base, api_key, kayitlar=None):
    """Modeli endpoint listesinden seçtir; liste alınamazsa elle sor.

    (model_kimligi, ham_kayit) döndürür. Kayıt, bağlam penceresi gibi ek
    alanları taşıyabildiği için birlikte dönüyor.
    """
    if kayitlar is None:
        io.tool_output()
        io.tool_output("Endpoint'teki modeller alınıyor...")
        kayitlar = modelleri_getir(api_base, api_key)

    if not kayitlar:
        io.tool_warning("Model listesi alınamadı; kimliği elle gir.")
        return (
            io.prompt_ask("Model kimliği (ör. qwen3-coder)", default="qwen3-coder").strip(),
            None,
        )

    secenekler = [(k["id"], k["id"]) for k in kayitlar]
    secenekler.append(("__elle__", "(listede yok, elle yazacağım)"))

    secim = _ask_choice(io, f"Model ({len(kayitlar)} tane bulundu)", secenekler)
    if secim == "__elle__":
        return io.prompt_ask("Model kimliği", default="").strip(), None

    kayit = next((k for k in kayitlar if k["id"] == secim), None)
    return secim, kayit


def _arac_destegini_bildir(io, api_base, api_key, model_id):
    """Fonksiyon çağırma desteğini deneyip sonucu kullanıcıya söyle.

    Agent modu buna bağlı. Desteklemeyen bir model sessizce tanımlanırsa
    belirtisi "model hiç araç çağırmıyor" oluyor ve sebebi görünmüyor.
    """
    io.tool_output()
    io.tool_output("Fonksiyon çağırma desteği deneniyor...")
    destek, aciklama = arac_destegi_dene(api_base, api_key, model_id)

    if destek is True:
        io.tool_output(f"  Araç çağırma çalışıyor ({aciklama}).")
    elif destek is False:
        io.tool_warning(f"  Model araç çağırmadı: {aciklama}.")
        io.tool_warning(
            "  Agent modu fonksiyon çağırmaya bağlı. Bu modelde araçlar"
            " çalışmayabilir; endpoint'te tool desteği açık mı diye bak."
        )
    else:
        io.tool_warning(f"  Deneme yapılamadı: {aciklama}. Tanım yine de yazılıyor.")


def run_setup(io, home=None):
    """Etkileşimli model tanımlama akışı.

    Yazılan dosyaların yollarını ve tanımlanan model adını döndürür.
    """
    home = Path(home) if home else Path.home()

    io.tool_output()
    io.tool_output("Model tanımlama. Boş bırakırsan köşeli parantezdeki değer kullanılır.")

    # Tek soru: adres. Şema, sondaki /models, eksik /v1 — hepsi düzeltiliyor.
    ham = io.prompt_ask(
        "Endpoint adresi (ör. http://sunucu:8000/v1)",
        default=os.environ.get("OPENAI_API_BASE", ""),
    )
    api_base = taban_adresi(ham)
    if not api_base:
        raise ModelSetupCancelled("endpoint adresi boş bırakıldı")
    if api_base != (ham or "").strip():
        io.tool_output(f"Adres: {api_base}")

    # Anahtar ancak gerekiyorsa sorulur. Önce anahtarsız denenir; kurum
    # endpoint'lerinin çoğu ağ içinden anahtarsız yanıt veriyor ve gereksiz
    # soru akışı uzatmaktan başka işe yaramıyor.
    api_key = ""
    kayitlar = modelleri_getir(api_base, api_key)
    if not kayitlar:
        io.tool_output("Model listesi anahtarsız alınamadı.")
        api_key = io.prompt_ask(
            "API anahtarı (gerekmiyorsa boş bırak)", default=os.environ.get("OPENAI_API_KEY", "")
        ).strip()
        if api_key:
            kayitlar = modelleri_getir(api_base, api_key)

    raw_name, kayit = _model_sec(io, api_base, api_key, kayitlar)
    if not raw_name:
        raise ModelSetupCancelled("model kimliği boş bırakıldı")

    # litellm sağlayıcısı her zaman openai/: OpenAI uyumlu /v1 ucu olan her
    # sunucu (vLLM, llama.cpp, Ollama'nın /v1'i, LiteLLM ağ geçidi) bu yoldan
    # doğru çalışıyor. Kullanıcı öneki kendisi yazdıysa iki kez eklemeyelim.
    model_name = raw_name if "/" in raw_name else "openai/" + raw_name

    # Pencere endpoint'ten okunabildiyse varsayılan o olsun; kullanıcı yine
    # değiştirebilir.
    bulunan = _pencere_bul(kayit) if kayit else None
    if bulunan:
        io.tool_output(f"Bağlam penceresi endpoint'ten okundu: {bulunan}")
    context = _ask_int(io, "Bağlam penceresi (token)", bulunan or DEFAULT_CONTEXT)
    max_output = _ask_int(io, "Azami çıktı (token)", DEFAULT_MAX_OUTPUT)

    _arac_destegini_bildir(io, api_base, api_key, raw_name)

    # --- yazma ---------------------------------------------------------------

    written = []

    conf_path = home / ".aider.conf.yml"
    conf = _read_yaml(conf_path)
    conf["model"] = model_name
    conf["edit-format"] = "agent"
    if api_base:
        conf["openai-api-base"] = api_base
    if api_key:
        conf["openai-api-key"] = api_key
    # Kurum modelleri aider'ın veritabanında olmadığı için uyarı basar.
    conf["show-model-warnings"] = False
    # İki yardımcı dosyayı conf gösteriyor; böylece ev dizininde üç ayrı nokta
    # yerine tek giriş noktası (bu dosya) ve tek dizin (~/.aider) kalıyor.
    conf["model-settings-file"] = str(home / ".aider" / "model.settings.yml")
    conf["model-metadata-file"] = str(home / ".aider" / "model.metadata.json")
    _write_private(conf_path, yaml.safe_dump(conf, allow_unicode=True, sort_keys=False))
    written.append(conf_path)

    ayar_dizini = home / ".aider"
    ayar_dizini.mkdir(parents=True, exist_ok=True)

    settings_path = ayar_dizini / "model.settings.yml"
    eski_settings = home / ".aider.model.settings.yml"
    settings = _read_yaml(settings_path if settings_path.is_file() else eski_settings)
    if not isinstance(settings, list):
        settings = []
    settings = [s for s in settings if s.get("name") != model_name]
    settings.append(
        {
            "name": model_name,
            "edit_format": "agent",
            # Agent modunda repo haritası kapalı: modelin Glob/Grep/Read'i var
            # ve harita her isteğe yeniden gömülüyor.
            "use_repo_map": False,
            "use_temperature": 0,
            "streaming": True,
        }
    )
    settings_path.write_text(
        yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    written.append(settings_path)

    meta_path = ayar_dizini / "model.metadata.json"
    eski_meta = home / ".aider.model.metadata.json"
    meta = _read_json(meta_path if meta_path.is_file() else eski_meta)
    meta[model_name] = {
        "max_input_tokens": context,
        "max_output_tokens": max_output,
        "input_cost_per_token": 0,
        "output_cost_per_token": 0,
        "litellm_provider": "openai",
        "mode": "chat",
        "supports_function_calling": True,
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    written.append(meta_path)

    # DİKKAT: eski dosya "artık okunmuyor" DEĞİL. main.generate_search_path_list
    # varsayılan adı her zaman arama listesine koyuyor, yani ~/.aider.model.*
    # hâlâ yükleniyor. Sıra listeyi ters çevirdiği için conf'un gösterdiği
    # dosya EN SONA düşüyor ve aynı model adı için eskisini eziyor — ama yalnızca
    # eskisinde tanımlı başka bir model varsa o hâlâ geçerli.
    for eski in (eski_settings, eski_meta):
        if eski.is_file():
            io.tool_warning(
                f"Eski dosya hâlâ okunuyor, yenisi onu eziyor; içeriği taşındı: {eski}"
            )

    return model_name, written
