---
name: rapor-uret
description: Toplanan veriyi dosyaya döken bir rapor istendiğinde kullan — biçim seçimi, CSV ve HTML üretimi. "csv çıkar", "rapor", "tabloya dök", "dosyaya yaz", "html rapor" isteklerinde tetiklenir. Excel (xlsx) ve PDF için `rapor-excel-pdf`.
---

Doğrulandı: AlmaLinux 10.2 (python 3.12) ve macOS — 2026-08-29

## Biçimi seçerken

| Biçim | Bağımlılık | Ne zaman |
|---|---|---|
| **CSV** | yok (stdlib `csv`) | Varsayılan. Excel açar, script işler, her yerde çalışır. |
| **HTML** | yok | Zengin görünüm gerekiyorsa. Tarayıcıdan yazdır → PDF. |
| **XLSX** | `openpyxl` | Çok sayfa, biçimlendirme, süzme gerekiyorsa |
| **PDF** | kurulum gerektirir | Gerçekten PDF *dosyası* isteniyorsa |

**Kullanıcı biçim belirtmediyse CSV üret.**

**"PDF olsun" denince önce HTML öner.** Ölçüldü: minimal bir RHEL 10 sunucuda
`pandoc`, `wkhtmltopdf`, `weasyprint`, `libreoffice`, `ps2pdf` **hiçbiri
kurulu değil** ve hiçbir Python PDF kütüphanesi yok. HTML üretip tarayıcıdan
yazdırmak çoğu ihtiyacı bağımlılıksız karşılar. Kullanıcı gerçekten dosya
istiyorsa `rapor-excel-pdf` becerisine geç.

Bağımlılık gerektiren bir biçim istendiğinde **önce kurulu mu bak**:

```bash
python3 -c "import openpyxl; print(openpyxl.__version__)"
```

Kurulu değilse ve ortam çevrimdışıysa kendiliğinden `pip install` deneme —
başarısız olur. Kullanıcıya söyle, CSV ya da HTML öner.

## CSV

Türkçe karakter ve Excel uyumu için `utf-8-sig` kullan — düz `utf-8` ile
Excel Türkçe harfleri bozuk gösterir.

```python
import csv

satirlar = [
    {"sunucu": "web01", "durum": "senkron", "sapma_ms": 12},
    {"sunucu": "db02", "durum": "SORUN", "sapma_ms": 4200},
]

with open("ntp_durum.csv", "w", newline="", encoding="utf-8-sig") as f:
    yazici = csv.DictWriter(f, fieldnames=list(satirlar[0]))
    yazici.writeheader()
    yazici.writerows(satirlar)
```

Ayraç: Türkçe Excel kurulumları genelde `;` bekler. Kullanıcı Excel'de
açacaksa `delimiter=";"` ver ya da sor.

## HTML — bağımlılıksız ve yazdırılabilir

```python
html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>NTP Durum Raporu</title>
<style>
 body {{ font-family: sans-serif; margin: 2rem; }}
 table {{ border-collapse: collapse; }}
 th, td {{ border: 1px solid #ccc; padding: 6px 10px; }}
 th {{ background: #eee; text-align: left; }}
 .sorun {{ background: #fdd; }}
 @media print {{ .sorun {{ background: #fdd !important;
                           -webkit-print-color-adjust: exact; }} }}
</style></head><body>
<h1>NTP Durum Raporu</h1>
<p>2026-08-29, <code>chronyc sources</code> çıktısından üretildi.</p>
<table><tr><th>Sunucu</th><th>Durum</th><th>Sapma</th></tr>
{"".join(
  f'<tr class="{"sorun" if s["durum"]=="SORUN" else ""}">'
  f'<td>{s["sunucu"]}</td><td>{s["durum"]}</td><td>{s["sapma_ms"]} ms</td></tr>'
  for s in satirlar)}
</table></body></html>"""
open("ntp_durum.html", "w", encoding="utf-8").write(html)
```

`@media print` bloğu olmadan tarayıcı arka plan renklerini basmaz; sorunlu
satırlar çıktıda kaybolur.

Veri kullanıcıdan ya da komut çıktısından geliyorsa HTML'e gömmeden önce
kaçır (`html.escape`), yoksa tablo bozulur.

## Her zaman

- Dosyayı **nereye** yazdığını mutlak yolla söyle
- Satır sayısını ve sorunlu kayıt sayısını raporla
- Yazdıktan sonra dosyanın oluştuğunu doğrula: `ls -la <dosya>`
- Var olan raporun üzerine yazmadan önce sor; ada tarih ekle:
  `ntp_durum_2026-08-29.csv`
- Rapora **ne zaman ve hangi komutla** toplandığını yaz; altı ay sonra
  bakan kişi bilsin
