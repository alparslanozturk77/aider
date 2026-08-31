---
name: sadelestir
description: Yazılmış kodu sadeleştirmek, tekrarları ayıklamak ve gereksiz katmanları kaldırmak için kullan. Hata aramaz, kalite bakar. "sadeleştir", "temizle", "refactor", "basitleştir", "tekrar var mı" isteklerinde tetiklenir.
---

Bu beceri **hata aramaz**. Doğruluk incelemesi için `kod-inceleme` kullan.

## 1. Zaten var mı?

En değerli sadeleştirme, yeniden yazılmış bir şeyi silmektir.

Yeni eklenen her yardımcı fonksiyon için kod tabanında Grep ile ara: aynı işi
yapan bir şey zaten var mı? Yardımcı modüllere, `utils`, `helpers`, `common`
benzeri yerlere bak.

## 2. Ölü ve gereksiz kod

- Kullanılmayan değişken, import, fonksiyon, parametre
- Hiçbir zaman gerçekleşmeyen koşullar
- Yalnızca tek yerden çağrılan ve hiçbir şey soyutlamayan sarmalayıcılar
- Aynı bilgiyi iki yerde tutan durum

## 3. Altitude — soyutlama seviyesi

Bir fonksiyon içinde farklı seviyeler karışmış mı? Üst seviye akışın ortasında
bayt seviyesi işlem varsa, o parça ayrı bir fonksiyona çıkmalı.

Tersi de geçerli: yalnızca bir yerden çağrılan, ismi çağrı yerinden daha az
şey anlatan bir soyutlama fazlalıktır. Satır içine al.

## 4. Çevredeki koda uyum

Değişiklik çevresindeki kod gibi görünüyor mu? Aynı isimlendirme, aynı hata
işleme kalıbı, aynı yorum yoğunluğu. Projenin deyimlerini kendi tercihinle
değiştirme.

## 5. Yorumlar

- Kodun ne yaptığını tekrarlayan yorum sil
- *Neden* böyle yapıldığını anlatan yorum kalsın
- Yanlış ya da güncelliğini yitirmiş yorum, yorumsuzluktan kötüdür

## Sınırlar

- **Davranışı değiştirme.** Sadeleştirme davranışı korumalıdır.
- Testleri çalıştır ve geçtiğini gör; geçmiyorsa geri al.
- İstenmemiş dosyalara yayılma. Kapsam neyse orada kal.

## Raporlama

Ne kaldırdığını ve neden kaldırdığını satır satır say. Testlerin çıktısını
göster.
