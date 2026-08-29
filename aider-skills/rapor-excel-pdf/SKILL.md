---
name: rapor-excel-pdf
description: Excel (xlsx) ya da PDF dosyası üretmen gerektiğinde kullan — bağımlılık kontrolü, çevrimdışı kurulum, Türkçe font sorunu. "excel", "xlsx", "pdf üret", "pdf dosyası", "openpyxl", "rapor pdf olsun" isteklerinde tetiklenir. Bağımlılıksız CSV/HTML için `rapor-uret`.
---

Doğrulandı: AlmaLinux 10.2 (python 3.12) — 2026-08-29

## Önce ne kurulu, onu ölç

Bağımlılık ortamdan ortama değişiyor. Ölçülen bir örnek: aynı anda skyup
sunucusunda `openpyxl` **var** ama `pandas` yok; geliştirme makinesindeki
sanal ortamda tam tersi. Varsayma, bak:

```bash
python3 - <<'EOF'
import importlib.util as u
for m in ["openpyxl", "fpdf", "reportlab", "pandas"]:
    print(m.ljust(10), "VAR" if u.find_spec(m) else "YOK")
EOF
```

Yoksa ve ortam çevrimdışıysa **kendiliğinden kurma** — kullanıcıya söyle ve
aşağıdaki yordamı öner.

## Excel (xlsx) — `openpyxl`

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
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
for i, _ in enumerate(basliklar, 1):
    ws.column_dimensions[get_column_letter(i)].width = 18

kirmizi = PatternFill("solid", start_color="FFC7CE")
for satir in ws.iter_rows(min_row=2):
    if satir[1].value == "SORUN":
        for h in satir:
            h.fill = kirmizi

wb.save("ntp_durum.xlsx")
```

Sayıları metin olarak yazma — `4200` yaz, `"4200 ms"` değil. Birim başlığa
girer; yoksa Excel'de sıralama ve toplama çalışmaz.

## PDF — önce şunu bil

**Minimal RHEL 10'da PDF üretecek hiçbir şey yok.** Ölçüldü: `pandoc`,
`wkhtmltopdf`, `weasyprint`, `libreoffice`, `ps2pdf` kurulu değil; Python
tarafında da `fpdf`, `reportlab` yok.

Yani PDF her zaman **bilinçli bir kurulum** demektir. Kullanıcıya bunu söyle
ve iki seçenek sun:

1. HTML üret, tarayıcıdan yazdır → PDF. Kurulum yok. (bkz. `rapor-uret`)
2. Gerçekten dosya gerekiyorsa `fpdf2` kur — saf Python, derleme gerektirmez.

`weasyprint` seçme: wheel'i saf Python ama çalışma anında `pango`, `cairo`,
`gdk-pixbuf` sistem kütüphanelerini arar; minimal RHEL'de zahmetlidir.

## PDF'te Türkçe font — kesin tuzak

`fpdf2`'nin yerleşik fontları latin-1'dir; `ş`, `ğ`, `İ` karakterlerinde
hata verir. Unicode bir TTF şart ve **yolunu sabit yazma**.

Ölçüldü: skyup'ta `/usr/share/fonts/dejavu/` **yok**, `fc-list` de kurulu
değil. Bulunan tek şey `/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf`.
Bu yüzden fontu ara, varsay değil:

```bash
find /usr/share/fonts -name "*.ttf" | head          # RHEL
ls /System/Library/Fonts/Supplemental/*.ttf | head  # macOS
```

```python
from fpdf import FPDF

pdf = FPDF()
pdf.add_page()
pdf.add_font("govde", "", "<bulunan-ttf-yolu>")
pdf.set_font("govde", size=14)
pdf.cell(0, 10, "NTP Durum Raporu", new_x="LMARGIN", new_y="NEXT")

pdf.set_font("govde", size=9)
for s in satirlar:
    pdf.cell(0, 6, f"{s['sunucu']:12} {s['durum']:10} {s['sapma_ms']} ms",
             new_x="LMARGIN", new_y="NEXT")

pdf.output("ntp_durum.pdf")
```

DejaVu isteniyorsa `dejavu-sans-fonts` paketi **baseos** deposunda —
EPEL gerektirmez, Satellite'ta hazır bulunur.

## Çevrimdışı kurulum

İki yol var; kurumda hangisinin serbest olduğunu kullanıcıya sor.

**RPM (Satellite üzerinden, tercih edilen):**

```bash
dnf list --available python3-openpyxl python3-reportlab
```

Ölçüldü: ikisi de **EPEL** deposunda. Kurumun Satellite'ında EPEL senkron
değilse bu yol kapalıdır — önce depo listesine bak.

**Wheel (internete çıkabilen bir makinede indir, taşı):**

```bash
pip download -d wheels openpyxl fpdf2
# hedef makinede:
pip install --no-index --find-links wheels openpyxl fpdf2
```

İkisi de saf Python wheel; platform ve Python sürümü belirtmeye,
derlemeye gerek yok.

**Paket kurmak yan etkilidir — onay al.** Banka ortamında sunucuya paket
kurmak değişiklik kaydı gerektirebilir.
