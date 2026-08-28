"""Program içinden adım adım model tanımlama.

/model-ekle komutunun arkasındaki mantık. Kullanıcıya endpoint tipini ve model
kimliğini sorar, sonra aider'ın ev dizinindeki üç yapılandırma dosyasını yazar:

    ~/.aider.conf.yml              model adı, endpoint adresi, anahtar
    ~/.aider.model.settings.yml    edit_format, repo-map, sıcaklık
    ~/.aider.model.metadata.json   bağlam penceresi

Ev dizinine yazılır, böylece tanım tüm projelerde geçerli olur. Anahtar içeren
dosya 0600 izniyle oluşturulur.
"""

import json
import os
from pathlib import Path

import yaml

# Endpoint tipleri: (etiket, litellm öneki, varsayılan taban adres, anahtar gerekli mi)
ENDPOINT_TYPES = [
    (
        "kurum",
        "Kurum içi OpenAI uyumlu endpoint (vLLM, LiteLLM gateway, TGI)",
        "openai/",
        "",
        True,
    ),
    (
        # DİKKAT: litellm'in 'ollama_chat/' sağlayıcısı araç sonucu mesajlarını
        # (role="tool") modele ulaştırmıyor; model sonucu hiç görmüyor ve aynı
        # aracı sonsuza dek çağırıyor. Ollama'nın OpenAI uyumlu ucu (/v1) ham
        # istekte doğru çalıştığı için agent modunda o yol kullanılıyor.
        "ollama",
        "Yerel Ollama (OpenAI uyumlu /v1 ucu üzerinden)",
        "openai/",
        "http://localhost:11434/v1",
        False,
    ),
    (
        "yerel",
        "Yerel OpenAI uyumlu sunucu (llama.cpp, vLLM)",
        "openai/",
        "http://localhost:8000/v1",
        False,
    ),
]

DEFAULT_CONTEXT = 262144
DEFAULT_MAX_OUTPUT = 8192


class ModelSetupCancelled(Exception):
    """Kullanıcı kurulumu yarıda bıraktı."""


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


def run_setup(io, home=None):
    """Etkileşimli model tanımlama akışı.

    Yazılan dosyaların yollarını ve tanımlanan model adını döndürür.
    """
    home = Path(home) if home else Path.home()

    io.tool_output()
    io.tool_output("Model tanımlama. Boş bırakırsan köşeli parantezdeki değer kullanılır.")

    kind = _ask_choice(
        io,
        "Endpoint tipi",
        [(k, desc) for k, desc, _, _, _ in ENDPOINT_TYPES],
    )
    _, _, prefix, default_base, needs_key = next(t for t in ENDPOINT_TYPES if t[0] == kind)

    io.tool_output()
    io.tool_output("Model kimliğini endpoint'ten öğrenmek için:")
    io.tool_output('  curl -s "$OPENAI_API_BASE/models" -H "Authorization: Bearer $OPENAI_API_KEY"')

    raw_name = io.prompt_ask("Model kimliği (ör. qwen3-coder)", default="qwen3-coder").strip()
    if not raw_name:
        raise ModelSetupCancelled("model kimliği boş bırakıldı")

    # Kullanıcı öneki kendisi yazdıysa iki kez eklemeyelim.
    model_name = raw_name if "/" in raw_name else prefix + raw_name

    api_base = io.prompt_ask("Endpoint adresi (sonu /v1)", default=default_base).strip()
    # Kullanıcı alanı temizlerse endpoint tipinin varsayılanına dön; adressiz
    # yapılandırma sessizce yanlış sunucuya (api.openai.com) gider.
    api_base = api_base or default_base

    api_key = ""
    if needs_key or api_base:
        api_key = io.prompt_ask("API anahtarı (endpoint istemiyorsa boş bırak)", default="").strip()

    context = _ask_int(io, "Bağlam penceresi (token)", DEFAULT_CONTEXT)
    max_output = _ask_int(io, "Azami çıktı (token)", DEFAULT_MAX_OUTPUT)

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
    _write_private(conf_path, yaml.safe_dump(conf, allow_unicode=True, sort_keys=False))
    written.append(conf_path)

    settings_path = home / ".aider.model.settings.yml"
    settings = _read_yaml(settings_path)
    if not isinstance(settings, list):
        settings = []
    settings = [s for s in settings if s.get("name") != model_name]
    settings.append(
        {
            "name": model_name,
            "edit_format": "agent",
            "use_repo_map": True,
            "use_temperature": 0,
            "streaming": True,
        }
    )
    settings_path.write_text(
        yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    written.append(settings_path)

    meta_path = home / ".aider.model.metadata.json"
    meta = _read_json(meta_path)
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

    return model_name, written
