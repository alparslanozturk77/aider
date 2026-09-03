#!/usr/bin/env python3
"""OpenAI uyumlu sahte endpoint — agent döngüsünü modelsiz sınamak için.

Neden var: agent döngüsünün doğruluğu modelin zekâsına bağlı değil. Araçlar
çalışıyor mu, `tool_calls` yanıtsız kalıyor mu, istek modelin penceresine
sığıyor mu — bunların hiçbiri için gerçek bir model gerekmiyor, ama bunlar
kullanıcının fiilen çarptığı hatalar.

Sunucu iki şey yapar:

1. Senaryodaki yanıtları sırayla döndürür (araç çağrısı, sonra düz metin).
2. **Gelen isteği denetler** ve ihlalleri ekrana yazar:
   - `tool_calls` taşıyan assistant mesajının her çağrısına `tool` yanıtı var mı
   - `tool` mesajı öncesinde eşleşen bir çağrı var mı
   - istek, bildirilen bağlam penceresine sığıyor mu

Üçüncüsü srvsatellite'te yaşanan hatanın ta kendisi: istek 16385 token'la
reddedildi, sınır 16384'tü.

Kullanım:

    python3 scripts/sahte_endpoint.py --port 8000 --pencere 16384 &
    aider --agent --model openai/sahte-model --openai-api-base http://127.0.0.1:8000/v1
"""

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# Token saymak için tokenizer yok; karakter/token oranı ölçülmüş en kötü değer.
# Amaç kesin sayı değil, sınırın aşıldığını yakalamak.
KARAKTER_BASINA_TOKEN = 2.0

AYAR = {"pencere": 16384, "senaryo": [], "sira": 0, "ihlal": 0}


def _token(mesajlar):
    return int(len(json.dumps(mesajlar, ensure_ascii=False)) / KARAKTER_BASINA_TOKEN)


def denetle(govde):
    """İsteği denetle; ihlalleri döndür."""
    sorunlar = []
    mesajlar = govde.get("messages") or []

    bekleyen = {}
    for i, m in enumerate(mesajlar):
        for cagri in m.get("tool_calls") or []:
            bekleyen[cagri.get("id")] = i
        if m.get("role") == "tool":
            cid = m.get("tool_call_id")
            if cid not in bekleyen:
                sorunlar.append(f"mesaj {i}: eşleşen çağrısı olmayan tool yanıtı ({cid})")
            else:
                bekleyen.pop(cid)
    for cid, i in bekleyen.items():
        sorunlar.append(f"mesaj {i}: yanıtsız tool_call ({cid}) — endpoint bunu reddeder")

    tahmin = _token(mesajlar)
    if tahmin > AYAR["pencere"]:
        sorunlar.append(f"istek pencereye sığmıyor: ~{tahmin} token > {AYAR['pencere']}")

    return sorunlar, tahmin, len(mesajlar)


def sonraki_yanit():
    senaryo = AYAR["senaryo"]
    i = AYAR["sira"]
    AYAR["sira"] += 1
    if i < len(senaryo):
        return senaryo[i]
    return {"icerik": "Senaryo bitti."}


def _mesaj(adim):
    if adim.get("arac"):
        return {
            "role": "assistant",
            "content": adim.get("icerik") or "",
            "tool_calls": [
                {
                    "id": f"cagri{AYAR['sira']}",
                    "type": "function",
                    "function": {
                        "name": adim["arac"],
                        "arguments": json.dumps(adim.get("argumanlar") or {}),
                    },
                }
            ],
        }
    return {"role": "assistant", "content": adim.get("icerik") or ""}


class Sunucu(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # kendi çıktımızı yazıyoruz

    def _yaz(self, kod, veri):
        govde = json.dumps(veri, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._yaz(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "sahte-model",
                            "object": "model",
                            "owned_by": "test",
                            "max_model_len": AYAR["pencere"],
                        }
                    ],
                },
            )
            return
        self._yaz(404, {"error": "yok"})

    def do_POST(self):
        uzunluk = int(self.headers.get("Content-Length") or 0)
        try:
            govde = json.loads(self.rfile.read(uzunluk) or b"{}")
        except ValueError:
            self._yaz(400, {"error": "bozuk json"})
            return

        sorunlar, tahmin, sayi = denetle(govde)
        etiket = f"[istek {AYAR['sira'] + 1}] {sayi} mesaj, ~{tahmin} token"
        if sorunlar:
            AYAR["ihlal"] += len(sorunlar)
            print(f"{etiket}  İHLAL:", file=sys.stderr)
            for s in sorunlar:
                print(f"    - {s}", file=sys.stderr)
        else:
            print(f"{etiket}  tamam", file=sys.stderr)
        sys.stderr.flush()

        # Pencere aşıldıysa gerçek endpoint gibi reddet.
        if tahmin > AYAR["pencere"]:
            self._yaz(
                400,
                {
                    "error": {
                        "message": (
                            f"You passed {tahmin} input tokens. However, the model's"
                            f" context length is only {AYAR['pencere']} tokens."
                        ),
                        "type": "invalid_request_error",
                    }
                },
            )
            return

        mesaj = _mesaj(sonraki_yanit())
        model = govde.get("model") or "sahte-model"

        # Akış üretimde kullanılan yol: aider varsayılan olarak stream=true
        # gönderiyor ve fork'un `_consume_stream`'i araç çağrılarını parça
        # parça birleştiriyor. Yalnızca akışsız yanıt vermek, asıl çalışan kod
        # yolunu hiç sınamamak demek.
        if govde.get("stream"):
            self._akis(mesaj, model)
            return

        self._yaz(
            200,
            {
                "id": "sahte",
                "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0, "message": mesaj, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": tahmin,
                    "completion_tokens": 8,
                    "total_tokens": tahmin + 8,
                },
            },
        )

    def _akis(self, mesaj, model):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def parca(delta, bitis=None):
            veri = {
                "id": "sahte",
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": bitis}],
            }
            self.wfile.write(b"data: " + json.dumps(veri, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.flush()

        parca({"role": "assistant"})

        icerik = mesaj.get("content") or ""
        if icerik:
            # Gerçek bir sunucu gibi kelime kelime akıt.
            for kelime in icerik.split(" "):
                parca({"content": kelime + " "})

        for i, cagri in enumerate(mesaj.get("tool_calls") or []):
            # Araç çağrısı da parçalı gelir: önce ad, sonra argümanlar.
            parca(
                {
                    "tool_calls": [
                        {
                            "index": i,
                            "id": cagri["id"],
                            "type": "function",
                            "function": {"name": cagri["function"]["name"], "arguments": ""},
                        }
                    ]
                }
            )
            argumanlar = cagri["function"]["arguments"]
            orta = len(argumanlar) // 2
            for parcacik in (argumanlar[:orta], argumanlar[orta:]):
                parca({"tool_calls": [{"index": i, "function": {"arguments": parcacik}}]})

        parca({}, bitis="tool_calls" if mesaj.get("tool_calls") else "stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def senaryo_ayristir(metin):
    """`Read:{"file_path":"x"} | metin:Bitti` biçimini adımlara çevir."""
    adimlar = []
    for parca in metin.split("|"):
        parca = parca.strip()
        if not parca:
            continue
        if parca.startswith("metin:"):
            adimlar.append({"icerik": parca[len("metin:") :].strip()})
            continue
        eslesme = re.match(r"^(\w+):(\{.*\})$", parca)
        if not eslesme:
            raise SystemExit(f"senaryo adımı anlaşılmadı: {parca}")
        adimlar.append({"arac": eslesme.group(1), "argumanlar": json.loads(eslesme.group(2))})
    return adimlar


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--pencere", type=int, default=16384)
    ap.add_argument(
        "--senaryo",
        default='metin:Merhaba, sahte endpoint çalışıyor.',
        help='Örn: \'Read:{"file_path":"a.txt"} | metin:Okudum.\'',
    )
    args = ap.parse_args()

    AYAR["pencere"] = args.pencere
    AYAR["senaryo"] = senaryo_ayristir(args.senaryo)

    print(
        f"sahte endpoint: http://127.0.0.1:{args.port}/v1  pencere={args.pencere}"
        f"  {len(AYAR['senaryo'])} adım",
        file=sys.stderr,
    )
    sys.stderr.flush()
    HTTPServer(("127.0.0.1", args.port), Sunucu).serve_forever()


if __name__ == "__main__":
    main()
