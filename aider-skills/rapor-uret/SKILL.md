---
name: rapor-uret
description: Toplanan veriyi dosyaya döken bir rapor istendiğinde kullan — CSV, Excel (xlsx), PDF ya da HTML. "csv çıkar", "excel", "xlsx", "pdf", "rapor", "tabloya dök", "dosyaya yaz" isteklerinde tetiklenir.
---

## Biçimi seçerken

| Biçim | Bağımlılık | Ne zaman |
|---|---|---|
| **CSV** | yok (stdlib `csv`) | Varsayılan. Excel açar, script işler, her yerde çalışır. |
| **XLSX** | `openpyxl` | Birden çok sayfa, biçimlendirme, dondurulmuş başlık gerekiyorsa |
| **PDF** | `fpdf2` | Paylaşılacak, değiştirilmemesi gereken rapor |
| **HTML** | yok | Hızlı ve zengin; tarayıcıdan PDF'e basılabilir |

**Kullanıcı biçim belirtmediyse CSV üret.** Bağımlılık gerektirmez ve
Excel'de doğrudan açılır.

Bağımlılık gerektiren bir biçim istendiğinde önce kurulu mu bak:

```bash
python3 -c "import openpyxl; print(openpyxl.__version__)"
```

Kurulu değilse ve ortam çevrimdışıysa **kendiliğinden pip install deneme** —
başarısız olur. Kullanıcıya söyle ve CSV öner. Kurulum gerekiyorsa aşağıdaki
çevrimdışı yordamı ver.

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

## Excel (xlsx)

```python
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active
ws.title = "NTP Durum"

basliklar = ["Sunucu", "Durum", "Sapma (ms)"]
ws.append(basliklar)
for h in ws[1]:
    h.font = Font(bold=True)

for s in satirlar:
    ws.append([s["sunucu"], s["durum"], s["sapma_ms"]])

ws.freeze_panes = "A2"                      # başlık sabit kalsın
ws.auto_filter.ref = ws.dimensions          # süzme açık
for i, _ in enumerate(basliklar, 1):        # sütun genişliği
    ws.column_dimensions[get_column_letter(i)].width = 18

wb.save("ntp_durum.xlsx")
```

Sorunlu satırları renklendirmek raporu okunur kılar:

```python
from openpyxl.styles import PatternFill
kirmizi = PatternFill("solid", start_color="FFC7CE")
for satir in ws.iter_rows(min_row=2):
    if satir[1].value == "SORUN":
        for h in satir:
            h.fill = kirmizi
```

## PDF

`fpdf2` en hafif seçenek ve saf Python.

```python
from fpdf import FPDF

pdf = FPDF()
pdf.add_page()
# Türkçe karakter için Unicode font ŞART. Yerleşik fontlar latin-1'dir
# ve 'ş', 'ğ', 'İ' karakterlerinde hata verir.
pdf.add_font("dejavu", "", "/usr/share/fonts/dejavu/DejaVuSans.ttf")
pdf.set_font("dejavu", size=14)
pdf.cell(0, 10, "NTP Durum Raporu", new_x="LMARGIN", new_y="NEXT")

pdf.set_font("dejavu", size=9)
for s in satirlar:
    pdf.cell(0, 6, f"{s['sunucu']:12} {s['durum']:10} {s['sapma_ms']} ms",
             new_x="LMARGIN", new_y="NEXT")

pdf.output("ntp_durum.pdf")
```

RHEL'de DejaVu fontu için: `dnf install dejavu-sans-fonts`. Font yoksa
`fc-list | grep -i dejavu` ile başka bir Unicode font bul.

**`weasyprint` kullanma.** Saf Python wheel'i var ama çalışma anında
`pango`, `cairo`, `gdk-pixbuf` sistem kütüphanelerini arar; çevrimdışı
minimal RHEL'de kurulumu zahmetlidir.

## HTML — bağımlılıksız zengin rapor

PDF bağımlılığı kurulamıyorsa en iyi alternatif. Tarayıcıdan yazdır → PDF.

```python
html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>
 body {{ font-family: sans-serif; }}
 table {{ border-collapse: collapse; }}
 th, td {{ border: 1px solid #ccc; padding: 6px 10px; }}
 th {{ background: #eee; }}
 .sorun {{ background: #fdd; }}
 @media print {{ .sorun {{ background: #fdd !important; -webkit-print-color-adjust: exact; }} }}
</style></head><body>
<h1>NTP Durum Raporu</h1>
<table><tr><th>Sunucu</th><th>Durum</th><th>Sapma</th></tr>
{"".join(
  f'<tr class="{"sorun" if s["durum"]=="SORUN" else ""}">'
  f'<td>{s["sunucu"]}</td><td>{s["durum"]}</td><td>{s["sapma_ms"]} ms</td></tr>'
  for s in satirlar)}
</table></body></html>"""
open("ntp_durum.html", "w", encoding="utf-8").write(html)
```

## Çevrimdışı kurulum

İnternete çıkabilen bir makinede indir, kuruma taşı:

```bash
pip download -d wheels openpyxl fpdf2
# hedef makinede:
pip install --no-index --find-links wheels openpyxl fpdf2
```

Hepsi saf Python wheel olduğu için platform ve Python sürümü belirtmene gerek
yok; derleme de gerekmez.

## Her zaman

- Dosyayı **nereye** yazdığını mutlak yolla söyle
- Satır sayısını ve sorunlu kayıt sayısını raporla
- Yazdıktan sonra dosyanın oluştuğunu doğrula: `ls -la <dosya>`
- Var olan bir raporun üzerine yazmadan önce sor; tarih ekle:
  `ntp_durum_2026-08-28.csv`
- Rapora **ne zaman ve hangi komutla** toplandığını yaz; altı ay sonra
  bakan kişi bilsin
