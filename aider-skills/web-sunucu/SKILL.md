---
name: web-sunucu
description: Nginx ya da Apache sorunlarını incelerken kullan. Yapılandırma doğrulama, 502/504, TLS sertifikası, SELinux. "nginx", "apache", "httpd", "502", "504", "bad gateway", "sertifika", "reverse proxy", "site açılmıyor" isteklerinde tetiklenir.
---

## Adım 0 — konteynerde mi?

`systemctl is-active nginx` **inactive** derken 80/443 dinleniyorsa nginx
konteynerdedir. Host'taki `nginx -t` o zaman konteynerin yapılandırmasını
sınamaz — host'ta bozuk görünen yapılandırma konteynerdeki sağlıklı nginx'i
ilgilendirmez. Ölçüldü: bir sunucuda host `nginx -t` hata verirken konteyner
`(healthy)` durumundaydı.

```bash
ss -tlnp | grep -E ':80 |:443 '     # süreç conmon → podman, docker-proxy → docker
podman ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}"
podman port -a                       # hangi konteyner hangi portu yayınlıyor
podman exec <ad> nginx -t
podman logs --tail 200 <ad>
```

Konteyner değilse aşağıdaki komutlar host'ta çalışır.

## Yapılandırma — değiştirmeden önce her zaman doğrula

```bash
nginx -t                      # sözdizimi testi
nginx -T                      # etkin yapılandırmanın tamamı
httpd -t                      # Apache
apachectl configtest
```

**`reload` ile `restart` farkı önemli.** `reload` yapılandırmayı yeniden okur,
açık bağlantıları korur. `restart` bağlantıları keser ve bozuk yapılandırmayla
servisi tamamen düşürür. Üretimde: önce `-t`, sonra `reload`.

## Teşhis

```bash
ss -tlnp | grep -E ':80 |:443 '
tail -n 200 /var/log/nginx/error.log
tail -n 200 /var/log/httpd/error_log
curl -sS -o /dev/null -w '%{http_code} %{time_total}s\n' -H 'Host: <alan>' http://127.0.0.1/
```

Neye bakılır:

- `upstream timed out` / `connect() failed` → **arka uç ayakta değil**, sorun
  web sunucusunda değil. Upstream adresini `nginx -T | grep -A3 upstream` ile
  bul, oraya `nc -zv <host> <port>` at.
- `502 Bad Gateway` → upstream çöktü ya da adres yanlış
- `504 Gateway Timeout` → upstream yavaş, `proxy_read_timeout` yetmiyor
- `403` + log'da `Permission denied` → dosya izni ya da SELinux

## TLS

```bash
openssl s_client -connect localhost:443 -servername <alan> </dev/null 2>&1 | head -20
openssl x509 -noout -enddate -subject -issuer -in <cert>
openssl x509 -noout -text -in <cert> | grep -A1 "Subject Alternative Name"
```

Sık hata: sertifika geçerli ama **SAN listesinde istenen alan adı yok** ya da
ara sertifika (chain) eksik. `s_client` çıktısında `verify error:num=20`
(unable to get local issuer) chain eksikliğini gösterir.

## SELinux — RHEL'de sık suçlu

Nginx/Apache'nin upstream'e bağlanmasını ya da statik dosya okumasını engeller.
Belirti: yapılandırma doğru, port açık, ama `Permission denied`.

```bash
ausearch -m avc -ts recent | grep -E 'httpd|nginx'
getsebool -a | grep httpd_can_network
ls -Z /var/www/html
```

Sık gereken boolean'lar: `httpd_can_network_connect` (reverse proxy),
`httpd_can_network_connect_db`, `httpd_read_user_content`.

Dosya etiketi yanlışsa `restorecon -Rv <yol>`, kalıcı kural gerekiyorsa
`semanage fcontext -a -t httpd_sys_content_t '<yol>(/.*)?'` sonra `restorecon`.

**SELinux'u asla devre dışı bırakma.** Banka ortamında CIS denetimine takılır;
boolean ya da fcontext ile çöz, gerekçesini yaz.

## Raporlama

Hangi katmanın suçlu olduğunu söyle. "502 alıyoruz" değil, "nginx ayakta,
upstream 10.0.3.14:8080'e `nc` ile bağlanılamıyor — sorun uygulama tarafında"
doğru rapordur.
