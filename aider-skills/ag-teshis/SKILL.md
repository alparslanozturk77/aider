---
name: ag-teshis
description: Ağ, güvenlik duvarı ve SELinux sorunlarını incelerken kullan. "bağlanamıyor", "port", "firewall", "selinux", "erişim yok", "timeout", "connection refused", "DNS" isteklerinde tetiklenir.
---

"Servis çalışıyor ama bağlanamıyorum" vakalarının RHEL'deki sessiz suçlusu
çoğu zaman SELinux'tur. Ağ katmanını aşağıdan yukarı ele al; her adımda
sonuç al, tahmin etme.

## 1. Servis gerçekten dinliyor mu

```bash
ss -tlnp | grep -E ':<port>'
systemctl is-active <servis>
```

Çıktıda adres önemli:

- `127.0.0.1:8080` → yalnızca yerel. Uzaktan erişilemez, sorun ağda değil
  **yapılandırmada**. Servisi `0.0.0.0` ya da gerçek IP'ye bağla.
- `0.0.0.0:8080` ya da `*:8080` → tüm arayüzlerde dinliyor
- Hiç satır yok → servis ayakta değil ya da başka portta

Bu adım "bağlanamıyorum" vakalarının yarısını burada bitirir.

## 2. Yerelden erişilebiliyor mu

```bash
curl -sS -m 5 -o /dev/null -w '%{http_code}\n' http://localhost:<port>/
nc -zv localhost <port>
```

Yerelden çalışıp uzaktan çalışmıyorsa sorun güvenlik duvarı, SELinux ya da
bind adresidir — servisin kendisi değil.

## 3. Güvenlik duvarı

```bash
firewall-cmd --state
firewall-cmd --list-all
firewall-cmd --list-ports
firewall-cmd --list-services
```

Port açık değilse (yan etkili, **onay al**):

```bash
firewall-cmd --add-port=8080/tcp --permanent
firewall-cmd --reload
```

`--permanent` olmadan yapılan değişiklik yeniden başlatmada kaybolur;
`--permanent` ile yapılan `--reload` olmadan etkin olmaz. İkisi de gerekir.

Bulut sunucusuysa ayrıca ağ güvenlik grubuna bak — `firewall-cmd` yeşil
görünürken trafiği bulut katmanı kesiyor olabilir.

## 4. SELinux — en sık atlanan katman

```bash
getenforce                          # Enforcing / Permissive / Disabled
ausearch -m avc -ts recent          # son engellemeler
grep -i denied /var/log/audit/audit.log | tail -20
```

`Enforcing` ve `avc denied` satırı varsa suçlu bulundu.

Sık karşılaşılanlar:

| Belirti | Boolean |
|---|---|
| nginx/httpd upstream'e bağlanamıyor | `httpd_can_network_connect` |
| httpd veritabanına bağlanamıyor | `httpd_can_network_connect_db` |
| Servis standart dışı portta dinleyemiyor | `semanage port -a` gerekir |
| NFS üzerinden dosya okunamıyor | `httpd_use_nfs` |

```bash
getsebool -a | grep httpd            # mevcut durum
setsebool -P httpd_can_network_connect on    # yan etkili, ONAY AL
semanage port -a -t http_port_t -p tcp 8080  # yan etkili
```

**`setenforce 0` yapıp bırakma.** Teşhis için geçici olarak denenebilir ama
çözüm değildir; sorunu doğruladıktan sonra geri al ve doğru boolean'ı ayarla.
Kalıcı olarak SELinux kapatmak güvenlik duruşunu düşürür.

## 5. İsim çözümleme ve yönlendirme

```bash
getent hosts <ad>                   # /etc/hosts + DNS birlikte
dig +short <ad>
resolvectl status | head -20
ip route get <hedef-ip>
traceroute -n -w1 -m10 <hedef>
```

`getent` çözüyor ama `dig` çözmüyorsa kayıt `/etc/hosts` içindedir.

## 6. Uzak uçtan bakış

```bash
nc -zv -w 5 <sunucu> <port>
curl -sS -m 5 -o /dev/null -w '%{http_code}\n' http://<sunucu>:<port>/
```

Hata mesajını ayırt et:

- **Connection refused** → paket ulaştı, o portta dinleyen yok
- **Connection timed out** → paket düştü; güvenlik duvarı ya da yönlendirme
- **No route to host** → yerel yönlendirme sorunu
- **Name or service not known** → DNS

Bu üç mesaj sorunu üç farklı katmana işaret eder; karıştırma.

## Raporlama

Hangi katmanda takıldığını söyle ve kanıtını göster. "Bağlanamıyor" yetmez:
"servis 127.0.0.1'e bağlı, o yüzden uzaktan erişilemiyor — `ss` çıktısı şu"
doğru rapordur.
