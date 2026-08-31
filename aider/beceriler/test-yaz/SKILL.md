---
name: test-yaz
description: Yeni ya da mevcut kod için test yazarken kullan. Projenin kendi test kurallarını keşfeder ve onlara uyar. "test yaz", "test ekle", "coverage" isteklerinde tetiklenir.
---

## 1. Projenin test kurallarını keşfet

Kendi tarzını dayatmadan önce projenin tarzını öğren:

1. Glob ile test dosyalarını bul: `**/test_*.py`, `**/*_test.go`, `**/*.test.ts`
2. En yakın komşu testi Read ile oku
3. Şunlara dikkat et: test çatısı (pytest/unittest/jest), dosya adlandırması,
   fixture yaklaşımı, assert stili, mock kütüphanesi

Yeni bir test bağımlılığı eklemeden önce projenin onu zaten kullandığını doğrula.

## 2. Neyi test edeceğine karar ver

Öncelik sırası:

1. **Mutlu yol** — temel davranış gerçekten çalışıyor mu
2. **Sınır durumları** — boş girdi, None, sıfır, tek eleman, çok büyük girdi
3. **Hata yolları** — geçersiz girdi doğru istisnayı fırlatıyor mu

Getter/setter gibi mantık içermeyen kodu test etme; sayı şişirmenin faydası yok.

## 3. Test yaz

- Her test tek bir şeyi doğrulasın
- Test adı ne doğruladığını anlatsın: `test_bos_liste_sifir_dondurur`
- Testler birbirinden bağımsız olsun — çalışma sırasına bağlı test yazma
- Global durumu değiştiren testte temizliği garantile (fixture/tearDown)

## 4. Çalıştır ve doğrula

Testleri Bash ile gerçekten çalıştır. Geçtiğini görmeden "testler geçiyor" deme.

Yeni testin gerçekten bir şey yakaladığını doğrula: testi geçici olarak
bozulacak şekilde değiştirip başarısız olduğunu gör, sonra geri al. Hiçbir
zaman başarısız olamayan test, test değildir.

## 5. Raporla

Kaç test eklendiğini ve çıktının son satırını göster. Başarısız test varsa
gizleme; çıktısıyla birlikte bildir.
