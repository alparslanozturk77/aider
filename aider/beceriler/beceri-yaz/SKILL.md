---
name: beceri-yaz
description: Sıfırdan yeni bir aider becerisi yazarken kullan. Beceri biçimini, tetikleme mantığını ve sık yapılan hataları anlatır. "beceri yaz", "skill ekle", "yeni beceri", "skill çalışmıyor" isteklerinde tetiklenir. Var olan beceriyi denetlemek ve düzeltmek için `beceri-gelistir`.
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
| `aider/beceriler/<ad>/SKILL.md` | programla gelen, herkes | evet (fork deposunda) |
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

## Çevrimdışı ortamda komut referansı

Model internete çıkamıyorsa, bilmediği bir aracın sözdizimini **arayamaz** —
uydurur. `hammer`, `ipa`, `subscription-manager` gibi araçlarda bu, çalışmayan
ya da yanlış şey yapan komutlar demektir.

Referansı hafızadan değil, aracın kendi `--help` çıktısından üret. Bunu elle
yapma — komut zaten var:

```
/beceri-uret hammer --host satellite --ad satellite-hammer
```

`--help` ağacını gezer, ham çıktıyı `aider-skills/<ad>/referans/yardim.md`
dosyasına yazar ve `SKILL.md` iskeletini kurar. Sen yalnızca gövdeyi
doldurursun; komutları referanstan alırsın, uydurmazsın. `--host` verilirse
program uzak sunucuda aranır.

Sonra her salt-okunur komutu gerçek sunucuda çalıştırarak doğrula; tam yordam
`beceri-gelistir` becerisinde.

Asıl değer komut listesinde değil, **çıktının nasıl okunacağında**: hangi alan
hangi sorunu gösterir, eşik nedir, ne zaman alarm verilir. Komutun kendisi
zaten `--help`'te var.

Doğruladığın sürümü ve tarihi yaz:

```markdown
Doğrulandı: Satellite 6.15, hammer 3.7.0 — 2026-08-28
```

## Sık yapılan hatalar

- Açıklamada *ne olduğunu* yazıp *ne zaman kullanılacağını* yazmamak
- Gövdeye insan için giriş paragrafı koymak — model talimat bekliyor
- Kod tabanına özgü gerçekleri beceriye gömmek; onlar `CLAUDE.md`'ye ait
- Aynı işi yapan ikinci bir beceri yazmak; önce `/skills` ile bak
- **Komut sözdizimini hafızadan yazmak.** Çevrimdışı bir modelde bu, kalıcı
  yanlış bilgi demektir. `--help` çıktısından üret ve çalıştırarak doğrula.
- Var olan bir beceriyi düzeltirken bu beceriyi kullanmak — o iş
  `beceri-gelistir`'in işi.
