---
name: beceri-yaz
description: Yeni bir aider becerisi yazarken ya da var olanı düzeltirken kullan. Beceri biçimini, tetikleme mantığını ve sık yapılan hataları anlatır. "beceri yaz", "skill ekle", "yeni beceri", "skill çalışmıyor" isteklerinde tetiklenir.
---

## Beceri nedir

Bir klasör ve içinde YAML frontmatter'lı bir `SKILL.md`. Sistem promptuna
yalnızca `ad: açıklama` satırı girer; gövde ancak model `Skill` aracını
çağırınca yüklenir. Bu yüzden onlarca beceri tanımlamak bağlam maliyeti
yaratmaz.

## Nereye yazılır

| Dizin | Kim görür | Depoya girer mi |
|---|---|---|
| `aider-skills/<ad>/SKILL.md` | takım | evet |
| `.aider/skills/<ad>/SKILL.md` | yalnız sen | hayır |

Paylaşılacak beceriyi `aider-skills/` altına yaz. `.aider/` ile başlayan yol
`.gitignore`'daki `.aider*` kuralına takılır ve depoya giremez.

İskelet için: `/skills new <ad>`

## Frontmatter

```yaml
---
name: beceri-adi
description: NE ZAMAN kullanılacağı + tetikleyici kelimeler
---
```

`description` **en kritik alandır.** Model beceriyi kullanıp kullanmayacağına
yalnızca bu satıra bakarak karar verir; gövdeyi o aşamada görmez.

İyi: `Bir değişikliği gözden geçirirken kullan. "incele", "review", "gözden
geçir" isteklerinde tetiklenir.`

Kötü: `Kod inceleme becerisi.` — ne zaman kullanılacağını söylemiyor.

Açıklaması olmayan beceri **sessizce atlanır**.

## Gövde nasıl yazılır

Gövde modele verilen talimattır, insana anlatım değil.

- **Somut ol.** "Dikkatli ol" bir talimat değildir. "Önce `git diff` çalıştır,
  sonra her değişen dosyayı Read ile oku" talimattır.
- **Sıra ver.** Numaralı adımlar, modelin atlamasını zorlaştırır.
- **Araç adı geç.** Read, Grep, Glob, Bash — hangi adımda hangisi.
- **Durma koşulu koy.** Ne zaman bitmiş sayılacağını söyle.
- **Sınır koy.** Neyi yapmayacağını da yaz; zayıf modeller kapsamı taşırır.

Uzunluk: 30-120 satır iyi bir aralık. Çok kısa olan yönlendirmez, çok uzun
olan bağlamı yer ve model ortasını kaçırır.

## Test et

1. `/skills` — beceri listede görünüyor mu?
2. Becerinin kapsamına giren bir istek yaz, model kendiliğinden `Skill`
   aracını çağırıyor mu?
3. Çağırmıyorsa sorun neredeyse her zaman `description`'dadır: tetikleyici
   kelimeleri ekle.

`SKILL.md`'yi düzenledikten sonra `/skills` diskten yeniden yükler; aider'ı
kapatmana gerek yok.

## Çevrimdışı ortamda komut referansı becerisi yazmak

Model internete çıkamıyorsa, bilmediği bir aracın sözdizimini **arayamaz** —
uydurur. `hammer`, `ipa`, `subscription-manager` gibi araçlarda bu, çalışmayan
ya da yanlış şey yapan komutlar demektir.

Çözüm: referansı hafızadan değil, **aracın kendi yardım çıktısından** üret.

### Yordam

Bu adımları becerinin kullanılacağı **gerçek sunucuda** yap.

**1. Aracın var olduğunu ve sürümünü doğrula.**

```bash
command -v hammer && hammer --version
```

Araç yoksa beceri yazma — önce kullanıcıya sor.

**2. Komut ağacını çıkar.**

```bash
hammer --help
hammer host --help
hammer host list --help
```

`ipa` için: `ipa help topics`, `ipa help commands`, `ipa <komut> --help`

Çıktıyı **oku**, ezberden yazma. Alt komut adları sürümden sürüme değişir.

**3. Yalnızca ihtiyaç duyulan yüzeyi al.**

`hammer` yüzlerce alt komut içerir; hepsini beceriye koyma. Kullanıcının
fiilen yaptığı işleri sor ve o kadarını belgele. Beceri gövdesi 120 satırı
aşıyorsa fazla geniş tutmuşsundur; domaine göre böl.

**4. Salt-okunur ile yan etkiliyi ayır.**

Referansta iki başlık aç. Yan etkili komutların yanına ne değiştirdiğini yaz.
Bu ayrım izin kurallarının da temeli olur.

**5. Her komutu çalıştırarak doğrula.**

Salt-okunur olanları gerçekten çalıştır ve çıktının beklediğin biçimde
olduğunu gör. Çalıştırmadığın komutu referansa **koyma**, ya da açıkça
"doğrulanmadı" diye işaretle.

**6. Çıktının nasıl okunacağını yaz.**

Asıl değer burada. Komutun kendisi `--help`'te zaten var; modelin bilmediği
şey çıktının ne anlama geldiği: hangi alan hangi sorunu gösterir, eşik değer
nedir, ne zaman alarm verilir.

### Beceriye sürüm ve tarih yaz

```markdown
Doğrulandı: Satellite 6.15, hammer 3.7.0 — 2026-08-28
```

Sürüm değişince referansın güncellenmesi gerektiğini bu satır hatırlatır.

## Sık yapılan hatalar

- Açıklamada *ne olduğunu* yazıp *ne zaman kullanılacağını* yazmamak
- Gövdeye insan için giriş paragrafı koymak — model talimat bekliyor
- Kod tabanına özgü gerçekleri beceriye gömmek; onlar `CLAUDE.md`'ye ait
- Aynı işi yapan ikinci bir beceri yazmak; önce `/skills` ile bak
- **Komut sözdizimini hafızadan yazmak.** Çevrimdışı bir modelde bu, kalıcı
  yanlış bilgi demektir. `--help` çıktısından üret ve çalıştırarak doğrula.
