---
name: kod-inceleme
description: Bir değişikliği ya da dosyayı gözden geçirirken kullan. Hata, güvenlik açığı ve sadeleştirme fırsatlarını sistematik olarak arar. "kod incele", "review", "gözden geçir", "değişikliği incele" gibi isteklerde tetiklenir.
---

Bir değişikliği incelerken şu sırayı izle.

## 1. Kapsamı belirle

Neyin değiştiğini gör:

- Git deposu varsa: `git diff` ve `git diff --stat`
- Belirli bir dosya isteniyorsa: Read ile tamamını oku

Neye baktığını bilmeden yorum yapma.

## 2. Doğruluk

Şu sırayla ara — en ciddi olandan başla:

- **Sınır durumları:** boş liste, None, sıfır, negatif sayı, tek elemanlı dizi
- **Hata yolları:** yakalanmayan istisna, yutulan hata (`except: pass`), yanlış hata tipi
- **Kaynak sızıntısı:** kapatılmayan dosya/soket, `with` kullanılmayan yerler
- **Eşzamanlılık:** paylaşılan durum, yarış koşulu
- **Off-by-one:** dilim sınırları, döngü aralıkları

Her bulgu için somut bir senaryo yaz: hangi girdi → hangi yanlış çıktı. Senaryo
yazamıyorsan bulgu değildir, bildirme.

## 3. Güvenlik

- Kullanıcı girdisi doğrudan SQL, kabuk komutu ya da dosya yoluna gidiyor mu?
- Kimlik bilgisi, token ya da anahtar koda gömülmüş mü?
- Yetki kontrolü atlanabiliyor mu?

## 4. Sadeleştirme

- Kod tabanında zaten var olan bir şey yeniden mi yazılmış? Grep ile doğrula.
- Kullanılmayan değişken, ölü kod, gereksiz katman var mı?
- Çevredeki kodun deyimlerine uyuyor mu?

## 5. Test kapsamı

Yeni davranışın testi var mı? Yoksa hangi testin yazılması gerektiğini söyle.

## Raporlama

Bulguları ciddiyet sırasına göre, en ciddisi başta olacak şekilde listele.
Her madde: `dosya:satır` — sorun — somut başarısızlık senaryosu.

Bulgu yoksa bunu açıkça söyle; doldurmak için önemsiz şeyler uydurma.
