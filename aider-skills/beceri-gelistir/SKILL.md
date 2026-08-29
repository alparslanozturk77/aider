---
name: beceri-gelistir
description: Var olan becerileri denetlerken ve iyileştirirken kullan. Komutları gerçek sunucuda çalıştırarak doğrulama, yanlış bilgiyi ayıklama, uzun beceriyi bölme. "beceriyi geliştir", "beceriyi doğrula", "skill'i gözden geçir", "beceri güncelle", "yanlış komut" isteklerinde tetiklenir. Sıfırdan yeni beceri yazmak için `beceri-yaz`.
---

Bir becerinin doğru olduğunu iddia etmenin tek ölçüsü, içindeki komutları
çalıştırmış olmaktır. Bu beceri o denetimin yordamıdır.

## 1. Hangi beceriyi denetleyeceğini seç

Öncelik sırası:

1. Kullanıcının son zamanlarda fiilen kullandığı beceri — hata oradan çıkar
2. İçinde "doğrulanmadı" işareti taşıyan bölümler
3. 4000 karakteri aşan beceriler — zayıf model gövdenin ortasını kaçırır
4. Yazıldığından beri ürün sürümü değişmiş olanlar (frontmatter'daki tarihe bak)

```bash
wc -c aider-skills/*/SKILL.md | sort -rn | head
grep -rn "doğrulanmadı" aider-skills/
```

## 2. Komutları gerçek sunucuda çalıştır

Bu adımları becerinin kullanılacağı **gerçek makinede** yap. Yerel Mac'te
çalışan bir komut RHEL'de olmayabilir; ölçülen örnekler: `lsof` yok,
`traceroute` yok (`tracepath` var), `subscription-manager` yalnız RHEL'de,
`docker` yok / `podman` var.

**Araç var mı ve sürümü ne:**

```bash
command -v hammer && hammer --version
for c in lsof traceroute tracepath ss nc podman docker; do
  command -v $c >/dev/null && echo "$c VAR" || echo "$c YOK"
done
```

Araç yoksa beceriden çıkar ya da alternatifini yaz.

**Komut ağacını yardım çıktısından üret, hafızadan değil:**

```bash
hammer --help
hammer host --help
hammer host list --help
```

`ipa` için: `ipa help topics`, `ipa help commands`, `ipa <komut> --help`.
Alt komut adları sürümden sürüme değişir; çıktıyı **oku**.

**Salt-okunur komutları gerçekten çalıştır** ve çıktının becerideki
açıklamayla uyuştuğunu gör. Yan etkili komutları çalıştırma; onların yanına
ne değiştirdiğini yaz.

Çalıştıramadığın komutu ya sil ya da açıkça işaretle:

```markdown
Doğrulanmadı — Satellite'a erişimim yok. Çalıştırmadan önce `--help` ile teyit et.
```

## 3. Yanlış bulguyu düzelt ve ölçümü yaz

Bulduğun uyuşmazlığı düzeltirken **ne ölçtüğünü** commit mesajına koy.
Aylar sonra "bu neden böyle" sorusunun cevabı orada olmalı.

Gerçek örnek: `servis-teshis` becerisi `systemctl is-active postgresql`
diyordu. Ölçüldüğünde `inactive` döndü ama 5432 dinleniyordu — servis podman
konteynerindeydi, dinleyen süreç `conmon`'du. Beceri "postgres kapalı" diye
yanlış rapor verirdi. Düzeltme, her şeyden önce çalışan bir konteyner tespit
adımı oldu.

Bu tür bulgular becerinin bir cümlesini değil, **akışını** değiştirir. Yanlış
bir gerçeği düzeltirken becerinin sırasını da gözden geçir.

## 4. Uzunluğu denetle

4000 karakter pratik sınır; 4B model 3.4k civarında gövdenin ortasını
kaçırmaya başlıyor. Aşıyorsa **domaine göre** böl, rastgele kesme:

- `depolama` (teşhis) + `disk-ekleme` (operasyon)
- `servis-teshis` (veri servisleri) + `web-sunucu` (nginx/apache)

Bölerken her iki becerinin `description`'ına diğerine işaret eden bir cümle
koy, yoksa model yanlış olanı yükler.

## 5. `description`'ı gözden geçir

Model beceriyi yalnız bu satıra bakarak seçer. Denetlerken sor:

- Kullanıcının gerçekten yazdığı kelimeler burada geçiyor mu?
- Yeni bölünmüş kardeş beceriye yönlendirme var mı?
- Kapsam dışı bırakılan şey yazıyor mu?

## 6. Bitirmeden önce

```bash
.venv/bin/python -m pytest tests/basic/test_agent.py -q
.venv/bin/python scripts/fork_dogrula.py
.venv/bin/python -m flake8 aider/agent/ tests/basic/test_agent.py
```

Beceri sayısı değiştiyse `CLAUDE.md` ve `AGENT.md` içindeki tabloyu ve sayıyı
güncelle.

## Değişmez kural

**Erişemediğin bir ürün için komut referansı yazma.** SEP, Cortex XDR,
kuruma özgü Rancher yapılandırması — bunlarda hafızadan yazılan sözdizimi
kalıcı yanlış bilgidir. Onun yerine **keşif yordamı** yaz: aracın nerede
aranacağı, `--help`'in nasıl alınacağı, hangi log'a bakılacağı. Model
sunucuda gerçek çıktıyı görüp devam eder.
