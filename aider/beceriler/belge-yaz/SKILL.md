---
name: belge-yaz
description: Dokümantasyon yazarken ya da güncellerken kullan — README, runbook, mimari notu, kurulum rehberi, karar kaydı. "dokümante et", "belge", "README", "runbook", "yaz şunu", "not al", "prosedür" isteklerinde tetiklenir.
---

## Önce türünü belirle

| Tür | Sorusu | Nerede durur |
|---|---|---|
| README | Bu nedir, nasıl başlarım | Depo kökü |
| Runbook | Şu olay olunca ne yapılır | `docs/runbook/` |
| Mimari notu | Neden böyle kurulmuş | `docs/` |
| Karar kaydı | Neyi neden seçtik | `docs/kararlar/` |
| Kurulum | Sıfırdan nasıl kurulur | `docs/kurulum.md` |

Yanlış türde yazılan belge okunmaz. Kullanıcı "dokümante et" dediyse ve tür
belirsizse sor.

## Var olanı önce oku

```bash
ls docs/ 2>/dev/null
find . -maxdepth 2 -name "*.md" -not -path "./node_modules/*"
```

Konuyu kapsayan bir belge zaten varsa **yenisini yazma, onu güncelle.** İkinci
bir belge yazmak, ikisinin de güncelliğini yitirmesi demektir.

Mevcut belgelerin biçimine uy: başlık düzeyi, dil, kod bloğu stili.

## Nasıl yazılır

**Okuyucuyu belirle.** Altı ay sonra bu ekibe katılan biri mi, sen mi, başka
takım mı? Bilinen varsayımlar okuyucuya göre değişir.

**Ne değil neden.** Komutun ne yaptığı komuttan zaten belli. Belgeye ait olan,
o komutun neden gerektiği ve alternatifin neden seçilmediği.

**Çalıştırılabilir olsun.** Komutları kopyalanabilir blok içinde ver, yer
tutucuları açıkça işaretle:

    ssh <sunucu-adi>          # <> ile yer tutucu belli olsun

**Doğrulama adımı koy.** Her prosedürün sonunda "işe yaradığını şuradan
anlarsın" satırı olmalı.

**Tarih ve sürüm.** Ortama bağlı her belgeye doğrulandığı tarihi ve sürümü yaz:

    Doğrulandı: RHEL 9.4, Rancher 2.9 — 2026-08-28

## Runbook biçimi

Runbook gece 3'te, panik hâlinde okunur. Uzun anlatım işe yaramaz.

```markdown
# Postgres bağlantı havuzu doldu

## Belirti
Uygulama "too many connections" hatası veriyor.

## Doğrula
    psql -c "SELECT count(*) FROM pg_stat_activity;"
    psql -c "SHOW max_connections;"

## Sebep
Genelde uzun süren `idle in transaction` oturumları.

## Çöz
1. Suçluları bul:
       psql -c "SELECT pid, now()-query_start FROM pg_stat_activity
                WHERE state = 'idle in transaction' ORDER BY 2 DESC;"
2. Uygulama ekibine haber ver — havuz sızıntısı olabilir.
3. Acilse tek tek sonlandır (VERİ KAYBI RİSKİ, önce onay al):
       psql -c "SELECT pg_terminate_backend(<pid>);"

## Sonra
Havuz ayarını gözden geçir. Tekrarlıyorsa alarm kur.
```

Sırası: belirti → doğrula → sebep → çöz → sonra.

## Yazarken kaçın

- "Kolayca", "basitçe", "sadece" — okuyucu takılırsa kendini aptal hisseder
- Ekran görüntüsüyle anlatılan komut — kopyalanamaz, aranamaz
- Güncelliğini yitirecek ayrıntı (kişi adı, geçici IP) — ya yazma ya işaretle
- Kod tabanından okunabilecek şeyi tekrarlamak — kod değişir, belge kalır

## Bittiğinde

Dosyayı **mutlak yolla** söyle. Var olan bir belgeyi değiştirdiysen neyi
değiştirdiğini özetle. Yeni belge oluşturduysan ve depoda bir içindekiler
dizini (README bağlantı listesi gibi) varsa ona da ekle.

Kalıcı bir proje kararı ya da kullanıcının çalışma tercihi ortaya çıktıysa
`Hatirla` aracıyla kaydet — belge okunmayabilir, bellek her oturumda yüklenir.
