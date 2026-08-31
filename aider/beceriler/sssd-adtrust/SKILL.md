---
name: sssd-adtrust
description: AD trust üzerinden gelen hesaplar login olamadığında kullan. SSSD teşhisi, önbellek temizleme ve servis yeniden başlatma. "login olamıyor", "giriş yapamıyor", "sssd", "ad trust", "servis hesabı", "kullanıcı çözülmüyor", "sssd restart" isteklerinde tetiklenir.
---

Bilinen tekrarlayan olay: **AD trust'lı domainden gelen servis hesapları
ara ara login olamıyor, SSSD yeniden başlatılınca düzeliyor.**

Bu runbook önce teşhis yaptırır. Yeniden başlatmak belirtiyi geçirir ama
sebebi gizler — ve tekrarlıyorsa sebep hâlâ oradadır.

## 0. Araçlar

```bash
rpm -q sssd-tools || sudo dnf install -y sssd-tools
```

`sssctl` ve `sss_cache` **`sssd-tools`** paketinden gelir ve varsayılan
kurulumda **yoktur** (doğrulandı: AlmaLinux/RHEL 10, baseos deposu).

## 1. Belirtiyi doğrula

Kullanıcının tam adını `kullanici@domain` biçiminde al ve sırayla dene:

```bash
sssctl user-checks <kullanici>@<domain>
id <kullanici>@<domain>
getent passwd <kullanici>@<domain>
```

`sssctl user-checks` en bilgilendiricidir: hem NSS hem PAM tarafını gösterir,
yani "kullanıcı görünüyor ama login olamıyor" durumunu ayırt eder.

| Sonuç | Anlamı |
|---|---|
| `sssctl` çözüyor, `id` de çözüyor | Sorun SSSD'de değil — uygulamaya/sshd'ye bak |
| `sssctl` çözüyor, `id` çözmüyor | NSS responder ya da önbellek |
| Hiçbiri çözmüyor | Domain erişimi ya da trust |
| Çözüyor ama PAM başarısız | PAM tarafı, HBAC kuralı olabilir |

## 2. SSSD sağlıklı mı

```bash
systemctl status sssd --no-pager
sssctl domain-list
sssctl domain-status <domain>
```

`domain-status` çıktısında **Online** bekleniyor. `Offline` ise SSSD domain
denetleyicisine ulaşamıyor demektir — o zaman sorun önbellek değil ağ/DNS'tir,
yeniden başlatmak çözmez (bir süre sonra tekrar eder).

```bash
journalctl -u sssd --since "30 min ago" --no-pager | tail -40
```

Aranacak satırlar: `Backend is offline`, `ldap_child`, `krb5_child`,
`Cannot contact any KDC`, `PAC`.

## 3. AD trust'a özgü kontroller

Trust ayakta mı (IdM sunucusunda):

```bash
ipa trust-show <ad-domain>
ipa trustdomain-find <ad-domain>
```

ID eşleme aralığı doğru mu — trust'lı domain kullanıcıları için UID/GID
aralığı tanımlı olmalı:

```bash
ipa idrange-find
```

**PAC responder**, AD trust'ta grup üyeliklerini çözen bileşendir ve kendi
servisi vardır:

```bash
systemctl status sssd-pac.service --no-pager
journalctl -u sssd-pac --since "1 hour ago" --no-pager | tail -20
```

Modern RHEL'de `sssd-nss`, `sssd-pam`, `sssd-pac` gibi responder'lar soket
etkinleştirmelidir (`indirect` durumda görünürler). Ana `sssd.service`
yeniden başlatılınca hepsi etkilenir.

## 4. Önce önbellek, sonra yeniden başlatma

Yeniden başlatmadan önce **daha hafif** olanı dene — tek kullanıcının
önbelleğini geçersiz kılar, servis kesintisi olmaz:

```bash
sudo sss_cache -u <kullanici>@<domain>
sssctl user-checks <kullanici>@<domain>      # düzeldi mi
```

Domain genelinde:

```bash
sudo sss_cache -E                            # tüm girdileri geçersiz kıl
```

Bu çözmüyorsa yeniden başlat (yan etkili, **onay al**):

```bash
sudo systemctl restart sssd
sssctl user-checks <kullanici>@<domain>
```

**Yeniden başlatmanın bedeli:** önbellek boşalır, o an kimlik doğrulamaya
çalışan herkes birkaç saniye bekler, ve çevrimdışı kimlik doğrulama için
tutulan bilgiler gider. Tek kullanıcı için tüm sunucuyu etkileme — önce
`sss_cache -u` dene.

Son çare, önbellek dosyalarını silmek (yan etkili, **onay al**):

```bash
sudo systemctl stop sssd
sudo rm -f /var/lib/sss/db/*
sudo systemctl start sssd
```

## 5. Tekrarlıyorsa sebebi ara

Sürekli yeniden başlatmak gerekiyorsa bu bir çözüm değil, bir semptomdur.
Şunlara bak:

- **Önbellek süresi:** `/etc/sssd/sssd.conf` içinde `entry_cache_timeout`,
  `ldap_enumeration_refresh_timeout`. Servis hesapları seyrek kullanılıyorsa
  önbellek süresi dolmuş olabilir.
- **Backend offline döngüsü:** `journalctl -u sssd | grep -c "Backend is offline"`
  yüksekse DNS ya da ağ kararsızdır; SSSD sürekli çevrimdışına düşüyordur.
- **Birden fazla DC:** SSSD bir DC'ye takılıp kalmış olabilir.
  `sssctl domain-status <domain>` hangi sunucuya bağlı olduğunu gösterir.
- **Saat kayması:** Kerberos 5 dakikadan fazla farkı reddeder.
  `chronyc tracking` ile kontrol et.
- **SSSD sürüm hatası:** `rpm -q sssd` ve Red Hat çözüm makalelerine bak;
  AD trust ile ilgili bilinen hatalar sürüme özgüdür.

Bulguyu kaydet: `Hatirla` aracıyla "hangi sunucuda, hangi domain, ne sıklıkla"
notu tut. Tekrar deseni sebebi gösterir.

## Uzak sunucuda çalıştırma

Kullanıcı "şu sunucuda sssd kontrol et" dediğinde `Ssh` aracını kullan ve
teşhis adımlarını tek tek gönder:

```
Ssh(host="<sunucu>", command="systemctl is-active sssd; sssctl domain-status <domain>")
Ssh(host="<sunucu>", command="sssctl user-checks <kullanici>@<domain>")
```

Sunucuya `root` ile bağlanılıyorsa `sudo` gereksizdir; değilse komutun başına
ekle. Hangi kullanıcıyla bağlandığını bilmiyorsan `Ssh(host=..., command="id -un")`
ile öğren.

Yeniden başlatma uzak sunucuda da yan etkilidir — **onay al**, ve kullanıcıya
o sunucuda o an kimlik doğrulayan başka kullanıcılar olabileceğini hatırlat.

Birden fazla sunucuda aynı sorun varsa `filo-durum-kontrolu` becerisine geç;
tek tek ssh yerine playbook ile topla.

## Raporlama

Şunları söyle: hangi adımda düzeldi (`sss_cache -u` mu, restart mı),
`domain-status` Online mıydı, ve loglarda tekrar eden bir satır var mıydı.

"Restart ettim, düzeldi" tek başına rapor değildir — kaçıncı kez olduğunu ve
sebep aramak için ne yaptığını da yaz.
