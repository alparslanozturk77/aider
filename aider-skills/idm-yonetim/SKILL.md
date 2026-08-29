---
name: idm-yonetim
description: Red Hat IdM / FreeIPA istemci kurulumu, kimlik doğrulama sorunları ve ipa komutlarında kullan. "idm", "ipa", "ipa-client", "freeipa", "kerberos", "kinit", "sssd", "domain", "kimlik doğrulama", "login olamıyor" isteklerinde tetiklenir.
---

## Kurulum öncesi kontroller

Bu adımlar atlanınca kurulum yarıda kalır ve makine yarı yapılandırılmış
durumda kalır — geri toplamak kurmaktan zordur.

```bash
hostnamectl                          # FQDN olmalı, kısa ad değil
getent hosts $(hostname -f)          # kendi adını çözebiliyor mu
timedatectl                          # NTP senkron OLMALI
```

**Saat kritiktir.** Kerberos varsayılan olarak 5 dakikadan fazla saat farkını
reddeder; bilet alınamaz ve hata mesajı bunu açıkça söylemez. Senkron değilse
önce `chronyc sources` ile düzelt; filoda topluca bakmak için
`filo-durum-kontrolu` becerisini kullan.

DNS keşfi için IdM sunucusunun SRV kayıtları çözülmeli:

```bash
dig +short -t SRV _ldap._tcp.<alan>
dig +short -t SRV _kerberos._tcp.<alan>
```

Çözülmüyorsa `--server` ile açıkça belirtmen gerekir.

Güvenlik duvarında istemci tarafından çıkış: 88 ve 464 (TCP+UDP, Kerberos),
389/636 (LDAP/LDAPS), 53 (DNS). Doğrulama için `ag-teshis` becerisindeki
`nc` yordamını kullan.

## Paketler

```bash
rpm -q ipa-client sssd authselect krb5-workstation
dnf list --available ipa-client
```

`kinit` ve `klist` **`krb5-workstation` paketinden gelir ve varsayılan
kurulumda yoktur** (doğrulandı: AlmaLinux 10.2). `sssd` ve `authselect`
genelde kuruludur.

## Kurulum

Yan etkili ve sistem geneli — **onay al**. Kurulum kimlik doğrulama
yapılandırmasını değiştirir; yanlış giderse makineye giremeyebilirsin.
**Ayrı bir oturumu açık tut.**

```bash
sudo dnf install -y ipa-client
sudo ipa-client-install \
    --domain=<alan> \
    --server=<idm-sunucu-fqdn> \
    --principal=<yetkili-kullanici> \
    --mkhomedir \
    --enable-dns-updates
```

Seçeneklerin sürüme göre değişebileceğini unutma; çalıştırmadan önce
doğrula:

```bash
ipa-client-install --help | head -40
```

Kurulum sonrası doğrulama:

```bash
id <domain-kullanicisi>
kinit <kullanici> && klist
sssctl domain-status <alan>
authselect current
```

Geri alma (yan etkili, **onay al**): `sudo ipa-client-install --uninstall`

> Bağlandığın sunucuda bunu çalıştırmak o makinedeki tüm domain kimlik
> doğrulamasını bozar. Yerel bir root parolan olduğundan emin ol.

## Günlük ipa komutları

`ipa` alt komutları fiili sonda taşır: `-find` ve `-show` **okur**, `-add`,
`-mod`, `-del` **değiştirir**.

```bash
ipa user-find <ad>
ipa user-show <kullanici> --all
ipa host-find <sunucu>
ipa group-show <grup>
ipa sudorule-find
ipa hbacrule-find
```

Alt komut adları sürümden sürüme değişir. Ezberden yazma:

```bash
ipa help topics
ipa help commands | grep -i <konu>
ipa <komut> --help
```

Yazan komutlar (`-add`, `-mod`, `-del`) **onaysız çalıştırılmaz**.
`ipa host-del` ve `ipa user-del` geri dönüşü zor kayıp yaratır.

## Kimlik doğrulama sorunu teşhisi

Sırayla:

```bash
systemctl status sssd --no-pager
sssctl domain-status <alan>
id <kullanici>                       # çözülüyor mu
getent passwd <kullanici>
kinit <kullanici>                    # bilet alınabiliyor mu
klist                                # bilet geçerli mi, süresi
journalctl -u sssd -n 100 --no-pager
```

Sık sebepler:

| Belirti | Sebep |
|---|---|
| `kinit` "Clock skew too great" | Saat farkı — NTP |
| `id` çözmüyor, `kinit` çalışıyor | SSSD önbelleği ya da domain yapılandırması |
| Ara ara çözmüyor | IdM sunucularından biri erişilemez |
| Kurulumdan sonra hiç çalışmıyor | `authselect current` yanlış profil |

SSSD önbelleğini temizlemek (yan etkili, tüm kullanıcıları etkiler,
**onay al**):

```bash
sudo systemctl stop sssd
sudo rm -f /var/lib/sss/db/*
sudo systemctl start sssd
```

## Raporlama

Hangi adımın başarısız olduğunu ve hata mesajının tamamını göster. IdM'de
belirti (login olamıyor) ile sebep (saat, DNS, güvenlik duvarı, SSSD) çoğu
zaman farklı katmanlardadır.
