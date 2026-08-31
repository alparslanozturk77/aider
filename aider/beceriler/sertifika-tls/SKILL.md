---
name: sertifika-tls
description: TLS sertifikası ve şifreli bağlantı incelerken kullan. Süre dolumu, alan adı eşleşmesi, zincir eksikliği, kurumsal CA güveni, HTTPS dışı portlar. "sertifika", "certificate", "openssl", "tls", "ssl", "https çalışmıyor", "sertifika süresi", "expired", "self signed", "unable to get local issuer" isteklerinde tetiklenir.
---

Doğrulandı: OpenSSL 3.5.5, AlmaLinux 10.2 — 2026-08-29

## Temel kalıp

```bash
echo | openssl s_client -connect <host>:<port> -servername <ad> 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates
```

İki ayrıntı atlanırsa iş görmez:

- **`echo |` ya da `</dev/null`** vermezsen `s_client` girdi bekleyip asılır.
- **`-servername`** SNI'yi taşır. Vermezsen sunucu varsayılan sertifikayı
  döndürür ve yanlış sertifikaya bakarsın. Her zaman ver.

Beklenen çıktı:

```
subject=CN=*.ornek.local
issuer=C=US, O=Ornek CA, CN=Ara CA
notBefore=Aug 23 04:58:25 2026 GMT
notAfter=Nov 21 04:58:24 2026 GMT
```

## Süre — otomasyona uygun kontrol

`-checkend <saniye>` çıkış koduyla cevap verir; betikte kullanılacak olan bu.

```bash
echo | openssl s_client -connect <host>:443 -servername <ad> 2>/dev/null \
  | openssl x509 -noout -checkend 2592000        # 30 gün
```

Ölçüldü: süre dolmayacaksa `Certificate will not expire`, çıkış **0**;
dolacaksa `Certificate will expire`, çıkış **1**. Yani `|| uyar` yazabilirsin.

## Alan adı eşleşmesi

Sertifikanın geçerli olması yetmez, **istenen adı kapsaması** gerekir.

```bash
openssl x509 -in cert.pem -noout -checkhost <alan>
openssl x509 -in cert.pem -noout -checkip <ip>
openssl x509 -in cert.pem -noout -ext subjectAltName
```

Ölçüldü: `Hostname <ad> does match certificate` / `... does NOT match
certificate` (çıkış 1). Tarayıcı hatasının en sık sebebi CN doğru olduğu hâlde
adın SAN listesinde olmamasıdır — CN artık yok sayılıyor, SAN'a bak.

## Zincir eksikliği — en sık teşhis hatası

```bash
echo | openssl s_client -connect <host>:443 -servername <ad> 2>&1 \
  | grep -E "Verification|Verify return code"
echo | openssl s_client -connect <host>:443 -servername <ad> -showcerts 2>/dev/null \
  | grep -c "BEGIN CERTIFICATE"        # zincir derinliği
```

`Verification: OK` ve `Verify return code: 0 (ok)` iyi durumdur.

**`error 20 ... unable to get local issuer certificate`** neredeyse her zaman
sunucunun ara sertifikayı göndermediği anlamına gelir — sertifika bozuk değil,
zincir eksik. Yeniden üretmek için (ölçüldü):

```bash
openssl verify leaf.pem                          # -> error 20
openssl verify -untrusted zincir.pem leaf.pem    # -> OK
```

Bazı istemciler eksik zinciri tolere eder (tarayıcı ara sertifikayı
önbellekten bulur), `curl` ve Java etmez — "tarayıcıda çalışıyor ama
uygulamada çalışmıyor" şikâyetinin sebebi budur.

## HTTPS olmayan portlar

`-starttls` ile önce düz bağlanıp sonra TLS'e geçilir. PostgreSQL'de
doğrulandı:

```bash
openssl s_client -connect <host>:5432 -starttls postgres </dev/null
```

`openssl s_client -help` çıktısındaki `-starttls val` desteklenen protokolleri
listeler (smtp, imap, ldap, xmpp ve diğerleri). Kullanmadan önce oradan teyit
et; sürümden sürüme değişir.

## Protokol ve şifre

```bash
echo | openssl s_client -connect <host>:443 -servername <ad> 2>/dev/null \
  | grep -E "^New|^Protocol|Cipher"
echo | openssl s_client -connect <host>:443 -tls1_2 2>&1 | grep -E "^New|error"
```

Sürüm zorlayıp bağlantının kurulup kurulmadığına bakmak "eski TLS kapalı mı"
sorusunun cevabıdır.

## Kurumsal CA'ya güven (RHEL ailesi)

Kurum CA'sı ile imzalı iç servisler `verify` hatası verir; çözüm CA'yı sistem
güven deposuna koymaktır, doğrulamayı kapatmak değil.

```bash
ls /etc/pki/ca-trust/source/anchors/
trust list | grep -i <kurum>
```

CA eklemek **yan etkilidir, onay iste**: dosyayı `anchors/` altına koyup
`update-ca-trust` çalıştırmak tüm sistemin güvendiği kök kümesini değiştirir.

Konteynerler sistem deposunu kullanmaz — podman için
`/etc/containers/certs.d/<registry>/ca.crt`, bkz. `nexus-registry`.

## Kubernetes / Rancher uçları

API ucu da düz bir TLS ucudur; yukarıdaki temel kalıbı `<api-host>:6443` ile
kullan. Rancher proxy'si üzerinden erişilen downstream kümede dönen sertifika
Rancher'ın olabilir — `issuer` satırı hangi tarafa baktığını söyler.

## Raporlama

Hangi kontrolün düştüğünü kanıtıyla yaz. "Sertifika sorunlu" değil: "21
Kasım'da doluyor (30 gün için OK), ama SAN listesinde `api.ornek.local` yok —
istemci hatasının sebebi bu."
