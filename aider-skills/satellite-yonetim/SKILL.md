---
name: satellite-yonetim
description: Red Hat Satellite sunucusunun sağlığını, içerik görünümlerini ve senkronizasyonu kontrol ederken kullan. "satellite", "hammer", "content view", "içerik görünümü", "capsule", "repo sync", "yama deposu", "aktivasyon anahtarı" isteklerinde tetiklenir.
---

> **Sürüm uyarısı.** `hammer` alt komutları Satellite sürümüne göre değişir.
> Aşağıdakiler Satellite 6.x'te kararlıdır ama çalıştırmadan önce doğrula:
> `hammer --help`, `hammer <konu> --help`. İlk kez farklı bir sürümle
> çalışıyorsan `beceri-yaz` yordamıyla kendi doğrulanmış referansını çıkar.

## 1. Sağlık kontrolü

```bash
hammer ping
```

Her bileşen için `Status: ok` bekleniyor. Bir tanesi bile `FAIL` ise
istemciler kayıt olamaz ya da yama alamaz.

| Bileşen | Ne yapar | FAIL ise |
|---|---|---|
| `candlepin` | Abonelik ve yetkilendirme | `subscription-manager register` çalışmaz |
| `candlepin_auth` | Kimlik doğrulama | Aynı |
| `pulp` / `pulp3` | İçerik depolama ve dağıtım | `dnf` istemcide boş depo görür |
| `foreman_tasks` | Arka plan görevleri | Publish/promote takılır |

Daha kapsamlı denetim:

```bash
satellite-maintain health check
satellite-maintain service status
```

`satellite-maintain` Satellite 6.4+ ile geldi; eski sürümlerde
`foreman-maintain` adıyla bulunur.

## 2. `hammer ping` FAIL verirse

Önce servisleri gör, körlemesine yeniden başlatma:

```bash
satellite-maintain service status
systemctl --failed
journalctl -u foreman -n 100 --no-pager
journalctl -u pulpcore-api -n 100 --no-pager
```

**En sık sebep disk doluluğudur.** Satellite içerik depoladığı için
`/var/lib/pulp` sessizce şişer:

```bash
df -h /var/lib/pulp /var/lib/pgsql /var
```

Doluysa `depolama` becerisine geç — servisleri yeniden başlatmak dolu diskte
çözmez, biraz sonra tekrar düşer.

Yeniden başlatma (yan etkili, **onay al**, Satellite kesintisi demektir):

```bash
satellite-maintain service restart
```

## 3. İçerik görünümü (Content View)

İçerik görünümü, belirli bir anda dondurulmuş depo setidir. Sunucu teslim
akışında önemi: istemci hangi yama setini göreceğini buradan alır.

```bash
hammer content-view list --organization "<org>"
hammer content-view info --name "<cv>" --organization "<org>"
hammer content-view version list --content-view "<cv>" --organization "<org>"
hammer lifecycle-environment list --organization "<org>"
```

Yayınlama ve terfi (yan etkili, **onay al** — üretim ortamındaki tüm
sunucuların göreceği yama setini değiştirir):

```bash
hammer content-view publish --name "<cv>" --organization "<org>"
hammer content-view version promote \
    --content-view "<cv>" \
    --version "<sürüm>" \
    --to-lifecycle-environment "<ortam>" \
    --organization "<org>"
```

Publish uzun sürer; görev durumunu izle:

```bash
hammer task list --search "state = running"
hammer task progress --id <görev-id>
```

## 4. Depo senkronizasyonu

```bash
hammer repository list --organization "<org>"
hammer repository info --name "<repo>" --product "<ürün>" --organization "<org>"
```

`Sync Status` ve son senkron tarihine bak. Eski bir senkron, istemcilerin
güncel yamayı görmemesi demektir — "dnf update bir şey bulmuyor" şikâyetinin
sık sebebi budur.

Senkron başlatma (yan etkili, uzun sürer ve disk yer):

```bash
hammer repository synchronize --name "<repo>" --product "<ürün>" --organization "<org>"
```

## 5. İstemci tarafı sorunlar

Bir sunucu Satellite'e kayıt olamıyor ya da yama görmüyorsa:

```bash
# istemcide
subscription-manager status
subscription-manager identity
subscription-manager repos --list-enabled
dnf repolist

# Satellite'te
hammer host list --search "name ~ <sunucu>"
hammer host info --name "<sunucu-fqdn>"
```

Sık sebepler:

| Belirti | Bakılacak |
|---|---|
| Kayıt olamıyor | `hammer ping` candlepin, aktivasyon anahtarı doğru mu |
| Depo listesi boş | İçerik görünümü / yaşam döngüsü ortamı ataması |
| Yama gelmiyor | Depo senkron tarihi, CV sürümü terfi edilmiş mi |
| Sertifika hatası | İstemci saati, `katello-ca-consumer` paketi |

## 6. Aktivasyon anahtarları

```bash
hammer activation-key list --organization "<org>"
hammer activation-key info --name "<anahtar>" --organization "<org>"
```

Anahtar hangi içerik görünümüne ve ortama bağlar, onu gösterir. Yanlış anahtar
sunucuyu yanlış yama setine bağlar — `sunucu-teslim` becerisinde kayıt adımı
bunu kullanır.

## Yapmayacakların

- `hammer content-view version promote` komutunu üretim ortamına onaysız
  çalıştırma; o ortamdaki her sunucunun yama setini değiştirir
- Depoları ya da içerik görünümlerini silme
- `satellite-maintain service restart` komutunu iş saatlerinde onaysız
  çalıştırma — kayıt ve yama trafiği kesilir

## Raporlama

`hammer ping` çıktısını olduğu gibi ver, hangi bileşenin `FAIL` olduğunu
işaretle. İçerik görünümü sorununda hangi CV'nin hangi ortama hangi sürümle
terfi edilmiş olduğunu göster — sorun neredeyse her zaman burada çıkar.
