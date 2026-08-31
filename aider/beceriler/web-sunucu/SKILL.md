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

Sertifika sorunları için `sertifika-tls` becerisine geç — süre, SAN eşleşmesi,
zincir eksikliği ve kurumsal CA güveni orada. Hızlı bakış:

```bash
echo | openssl s_client -connect localhost:443 -servername <alan> 2>/dev/null \
  | openssl x509 -noout -subject -dates -ext subjectAltName
```

## SELinux — RHEL'de sık suçlu

Yapılandırma doğru, port açık, ama `Permission denied` ya da upstream'e
bağlanamıyor:

```bash
sestatus | grep -i "current mode"
ausearch -m avc -ts recent | grep -E 'httpd|nginx'
```

Düzeltme (boolean, port etiketi, `restorecon`) için `selinux` becerisine geç.
En sık gereken boolean `httpd_can_network_connect`.

## Raporlama

Hangi katmanın suçlu olduğunu söyle. "502 alıyoruz" değil, "nginx ayakta,
upstream 10.0.3.14:8080'e `nc` ile bağlanılamıyor — sorun uygulama tarafında"
doğru rapordur.
