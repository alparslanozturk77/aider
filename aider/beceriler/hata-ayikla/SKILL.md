---
name: hata-ayikla
description: Bir hata, çöken test ya da beklenmeyen davranış araştırırken kullan. Tahmin etmek yerine kanıt toplamayı dayatır. "hata", "çalışmıyor", "bug", "neden böyle", "test kırıldı", "debug" isteklerinde tetiklenir.
---

En sık yapılan hata, ilk makul açıklamayı doğru sanıp onu düzeltmeye
girişmektir. Bu beceri buna karşı bir disiplindir.

## 1. Hatayı gör

Rapor edilen belirtiyi **kendi gözünle** üret. Komutu çalıştır, testi çalıştır,
tam hata çıktısını al.

Üretemiyorsan, düzeltmeye başlama. Önce nasıl üretileceğini sor ya da bul.
Üretemediğin bir hatayı düzelttiğini iddia edemezsin.

## 2. Tam çıktıyı oku

Yığın izinin **en alt** satırından başla, en üstünden değil. İlk okunan satır
genelde belirtiyi verir, kaynağı değil.

- Hangi dosya ve satır?
- Hangi değer beklenmiyordu?
- Bu koda hangi yoldan gelindi?

## 3. Hipotez kur, sonra sına

Tek bir açıklama yaz ve onu **yanlışlayacak** bir gözlem tasarla.

Kanıt toplama yolları:
- Şüpheli değeri Read ile oku ya da geçici bir print/log ekle
- Grep ile o değerin nerede atandığını bul
- `git log -S "<ifade>"` ile ne zaman değiştiğini bul
- Testi tek başına, sonra hep birlikte çalıştır — fark varsa durum sızıntısı var

Hipotez tutmadıysa **bırak**, yenisini kur. Aynı hipotezi zorlamaya devam etme.

## 4. Kök nedeni düzelt

Belirtiyi susturmak düzeltme değildir. `except: pass` eklemek, `None`
kontrolü ile üstünü örtmek, testi devre dışı bırakmak — bunlar hatayı
gizler, çözmez.

Kök nedene ulaşamadıysan bunu açıkça söyle ve geçici çözüm olduğunu belirt.

## 5. Doğrula

- Hatanın gittiğini **çalıştırarak** gör
- Tüm test takımını çalıştır — düzeltme başka bir şeyi kırmış olabilir
- Bu hatayı yakalayacak bir test ekle; testi düzeltmeden önceki hâlde
  çalıştırıp gerçekten başarısız olduğunu doğrula

## Raporlama

Şunları söyle: belirti neydi, kök neden neydi, ne değiştirdin, nasıl doğruladın.
Araştırma sırasında elediğin yanlış hipotezleri de bir cümleyle geç — aynı yolu
tekrar yürümeyi önler.
