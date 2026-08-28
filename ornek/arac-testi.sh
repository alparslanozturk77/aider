#!/usr/bin/env bash
# Bir endpoint'in agent modu için uygun olup olmadığını sınar.
#
#   ./ornek/arac-testi.sh <model-adi> [api-base] [api-key]
#
# Örnekler:
#   ./ornek/arac-testi.sh qwen3-coder https://llm.kurum.local/v1 $KURUM_TOKEN
#   ./ornek/arac-testi.sh gemma4:e4b  http://localhost:11434/v1  ollama
#
# İki şeyi ayrı ayrı sınar:
#   1. Model bir aracı ÇAĞIRABİLİYOR mu (tool_calls alanı dönüyor mu)
#   2. Model araç SONUCUNU GÖREBİLİYOR mu (round-trip)
#
# İkisi de geçmezse agent modu çalışmaz. Birincisi geçip ikincisi kalırsa
# model sonsuz döngüye girer.

set -u

MODEL="${1:-}"
BASE="${2:-${OPENAI_API_BASE:-http://localhost:11434/v1}}"
KEY="${3:-${OPENAI_API_KEY:-yer-tutucu}}"

if [ -z "$MODEL" ]; then
    echo "Kullanım: $0 <model-adi> [api-base] [api-key]" >&2
    exit 1
fi

BASE="${BASE%/}"
URL="$BASE/chat/completions"
PY="$(command -v python3 || command -v python)"

echo "model : $MODEL"
echo "uc    : $URL"
echo

TOOL='{"type":"function","function":{"name":"get_weather","description":"Bir sehrin hava durumunu getirir","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}'

# --- 1. Arac cagirabiliyor mu -----------------------------------------------

echo "1) Araç çağırma"
Y1=$(curl -s --max-time 180 "$URL" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KEY" \
    -d "{\"model\":\"$MODEL\",\"stream\":false,\"tool_choice\":\"auto\",
         \"messages\":[{\"role\":\"user\",\"content\":\"Istanbul'da hava nasil?\"}],
         \"tools\":[$TOOL]}")

CAGIRDI=$(printf '%s' "$Y1" | "$PY" -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: print("PARSE"); raise SystemExit
if "error" in d:
    print("API:" + str(d["error"])[:120]); raise SystemExit
try: m=d["choices"][0]["message"]
except Exception: print("SEKIL"); raise SystemExit
print("EVET" if m.get("tool_calls") else "HAYIR")
')

case "$CAGIRDI" in
    EVET)  echo "   tamam — tool_calls alanı döndü" ;;
    HAYIR) echo "   BAŞARISIZ — model yanıt verdi ama tool_calls yok."
           echo "   Muhtemel sebep: sunucuda araç ayrıştırıcı kapalı."
           echo "     vLLM  : --enable-auto-tool-choice --tool-call-parser hermes"
           echo "     Ollama: modelin sablonu tool desteklemiyor olabilir"
           echo
           echo "   Modelin ham yanıtı:"
           printf '%s' "$Y1" | "$PY" -c 'import json,sys;print("     "+repr((json.load(sys.stdin)["choices"][0]["message"].get("content") or "")[:200]))' 2>/dev/null
           exit 1 ;;
    PARSE) echo "   BAŞARISIZ — yanıt JSON değil. Adres doğru mu?"; exit 1 ;;
    SEKIL) echo "   BAŞARISIZ — yanıt beklenen biçimde değil."; exit 1 ;;
    API:*) echo "   BAŞARISIZ — ${CAGIRDI#API:}"; exit 1 ;;
esac

# --- 2. Arac sonucunu goruyor mu --------------------------------------------

echo
echo "2) Araç sonucunu görme (round-trip)"
Y2=$(curl -s --max-time 180 "$URL" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KEY" \
    -d "{\"model\":\"$MODEL\",\"stream\":false,\"tool_choice\":\"auto\",
         \"messages\":[
           {\"role\":\"user\",\"content\":\"Istanbul'da hava nasil?\"},
           {\"role\":\"assistant\",\"content\":\"\",\"tool_calls\":[{\"id\":\"c1\",\"type\":\"function\",\"function\":{\"name\":\"get_weather\",\"arguments\":\"{\\\"city\\\":\\\"Istanbul\\\"}\"}}]},
           {\"role\":\"tool\",\"tool_call_id\":\"c1\",\"content\":\"Durum kodu ZUMRUT7788, gunesli\"}
         ],
         \"tools\":[$TOOL]}")

GORDU=$(printf '%s' "$Y2" | "$PY" -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: print("PARSE"); raise SystemExit
if "error" in d: print("API:" + str(d["error"])[:120]); raise SystemExit
m=d["choices"][0]["message"]
txt=(m.get("content") or "").lower()
# Modelin donusturemeyecegi bir isaret: sayilari ve kelimeleri model yeniden
# yazabiliyor, bu diziyi yazamaz.
if "zumrut7788" in txt or "zumrut 7788" in txt: print("EVET")
elif m.get("tool_calls"): print("DONGU")
else: print("HAYIR:" + repr(txt[:150]))
')

case "$GORDU" in
    EVET)  echo "   tamam — model araç sonucunu okudu ve yanıtladı" ;;
    DONGU) echo "   BAŞARISIZ — model sonucu görmedi, aracı tekrar çağırdı."
           echo "   Agent modunda sonsuz döngüye girer."
           echo "   litellm 'ollama_chat/' sağlayıcısı bu hatayı veriyor;"
           echo "   'openai/' öneki + --openai-api-base ile dene."
           exit 1 ;;
    *)     echo "   BAŞARISIZ — ${GORDU}"; exit 1 ;;
esac

echo
echo "SONUÇ: bu model agent modu için uygun."
echo
echo "  aider --agent --model openai/$MODEL \\"
echo "        --openai-api-base $BASE --openai-api-key <anahtar>"
