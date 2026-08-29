---
name: sunucu-teslim
description: Yeni sunucu devralma, Satellite'e kaydetme, güncelleme ve ilgili birime teslim akışında kullan. "yeni sunucu", "teslim", "devral", "satellite", "kaydet", "subscription", "abonelik", "güncelle", "hazırla" isteklerinde tetiklenir.
---

## Bağlam

Sunucular **CIS uyumlu, kurumsal regülasyona uygun RHEL 10 şablonundan**
kuruluyor. Bu şu anlama gelir:

- NTP, sıkılaştırma ve temel yapılandırma **zaten hazır** — yeniden yapma
- AD ekibi DNS A kaydını girer, sunucu sana öyle gelir
- Güvenlik duvarı izinlerini FW ekibi verir — sen açmazsın, **talep edersin**

Senin işin: devralma kontrolü → Satellite kaydı → güncelleme → teslim.

Şablonun getirdiği bir şeyi "eksik" sanıp yeniden yapılandırma. Bir ayar
beklediğinden farklıysa önce şablonda öyle mi diye sor; CIS gereği bilinçli
olarak öyle bırakılmış olabilir.

## 1. Devralma kontrolü

Kendi işine başlamadan önce, önceki ekiplerin işini doğrula. Bir eksik varsa
**o ekibe geri gider**, sen düzeltmezsin.

```bash
hostnamectl                                  # FQDN doğru mu
getent hosts $(hostname -f)                  # DNS A kaydı çözülüyor mu
dig +short $(hostname -f)                    # AD ekibinin kaydı
timedatectl                                  # NTP senkron mu
chronyc sources -v | head                    # kaynak var mı, '^*' satırı
cat /etc/os-release | grep VERSION_ID        # beklenen sürüm mü
```

Sık çıkan eksikler ve kime ait:

| Eksik | Kime |
|---|---|
| DNS A kaydı yok / yanlış | AD ekibi |
| Ters DNS (PTR) yok | AD ekibi |
| NTP senkron değil | şablon/sanallaştırma |
| Beklenen port kapalı | FW ekibi (talep aç) |

## 2. Satellite kaydı

```bash
subscription-manager status
subscription-manager identity                # zaten kayıtlı mı
```

Zaten kayıtlıysa tekrar kaydetme; şablondan gelen kayıt olabilir.

Kayıt (yan etkili, **onay al**):

```bash
subscription-manager register \
    --org=<organizasyon> \
    --activationkey=<aktivasyon-anahtari>
```

Aktivasyon anahtarı hangi içerik görünümünü ve depoları vereceğini belirler —
yanlış anahtar yanlış yama setine bağlar. Anahtarı tahmin etme, kurulum
talebindeki değeri kullan.

Doğrulama:

```bash
subscription-manager status                  # Overall Status: Current
subscription-manager repos --list-enabled | grep -E '^Repo ID'
dnf repolist
```

Kayıt başarısız olursa sorun istemcide değil Satellite'te olabilir:
`satellite-yonetim` becerisine geç ve `hammer ping` ile candlepin'i kontrol et.

> Bu bölümdeki seçenekler Satellite sürümüne göre değişebilir. Çalıştırmadan
> önce `subscription-manager register --help` ile doğrula; ilk kez farklı bir
> Satellite sürümüyle çalışıyorsan `beceri-yaz` yordamıyla kendi referansını
> çıkar.

## 3. Güncelleme

```bash
dnf check-update                             # önce ne geleceğini gör
dnf update --security --assumeno             # kuru çalıştırma
```

Uygulama (yan etkili, **onay al**):

```bash
dnf update -y
needs-restarting -r                          # yeniden başlatma gerekiyor mu
```

`needs-restarting -r` sıfırdan farklı dönerse çekirdek ya da temel kütüphane
güncellenmiştir; yeniden başlatma gerekir. Bunu **teslimden önce** yap,
teslim ettiğin birime bırakma.

Yeniden başlatma sonrası:

```bash
uptime                                       # gerçekten yeniden başladı mı
systemctl --failed                           # açılışta düşen servis var mı
journalctl -p err -b --no-pager | tail -20
```

`systemctl --failed` boş olmalı. Değilse teslim etme, önce çöz.

## 4. Teslim öncesi son kontrol

```bash
subscription-manager status
dnf repolist
timedatectl
systemctl --failed
df -h
free -h
getenforce                                   # CIS şablonunda Enforcing olmalı
firewall-cmd --list-all
```

`getenforce` **Enforcing** dönmeli. `Permissive` ya da `Disabled` ise şablon
bozulmuş demektir — teslim etme, araştır. Bunu sen kapatmadıysan biri
kapatmıştır ve regülasyon ihlalidir.

## 5. Teslim raporu

Teslim ettiğin birime şunları yaz:

- FQDN ve IP
- RHEL sürümü ve çekirdek sürümü (`uname -r`)
- Satellite kaydı: organizasyon ve içerik görünümü
- Uygulanan güncellemelerin tarihi, yeniden başlatıldı mı
- Açık portlar (`firewall-cmd --list-all`) — ek port gerekiyorsa FW ekibine
  talep açmaları gerektiğini belirt
- Bilinen eksik ya da beklemede olan bir şey varsa açıkça

Rapor `rapor-uret` becerisiyle CSV ya da HTML olarak da üretilebilir.

## Yapmayacakların

- SELinux'u kapatma, `getenforce` çıktısını değiştirme
- Güvenlik duvarına kalıcı kural ekleme — o FW ekibinin işi
- Şablondan gelen sıkılaştırma ayarlarını "kolaylık olsun" diye gevşetme
- Parola politikası, `sshd_config`, `auditd` yapılandırmasına dokunma

Bunların hepsi CIS uyumluluk denetiminde çıkar ve sunucu geri gelir.
