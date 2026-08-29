---
name: ag-teshis
description: Ağ ve güvenlik duvarı sorunlarını incelerken kullan — dinleme, port, firewalld, DNS, yönlendirme. "bağlanamıyor", "port", "firewall", "erişim yok", "timeout", "connection refused", "DNS" isteklerinde tetiklenir. SELinux engeli için `selinux`, TLS için `sertifika-tls`.
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
sestatus | grep -i "current mode"
ausearch -m avc -ts recent
```

`Enforcing` ve `avc denied` satırı varsa suçlu bulundu — düzeltme için
`selinux` becerisine geç (boolean, port etiketi, dosya bağlamı).

`Permissive` ise SELinux engellemiyor; sorun başka katmanda, aramaya devam et.

## 5. İsim çözümleme ve yönlendirme

```bash
getent hosts <ad>                   # /etc/hosts + DNS birlikte
dig +short <ad>
cat /etc/resolv.conf                # hangi sunucuya soruluyor
ip route get <hedef-ip>
tracepath -n <hedef>                # traceroute minimal kurulumda yok
```

`getent` çözüyor ama `dig` çözmüyorsa kayıt `/etc/hosts` içindedir.

`resolvectl status` **her makinede çalışmaz** — ölçüldü, systemd-resolved
etkin olmayan bir RHEL 10'da `Failed to get global data ... unknown unit`
veriyor. Önce `systemctl is-active systemd-resolved`, değilse
`/etc/resolv.conf`'a bak.

## 6. Uzak uçtan bakış

```bash
nc -zv -w 5 <sunucu> <port>              # tek port
nc -zv -w 2 <sunucu> 80 443 8080         # birden çok port
for p in 88 389 443 636; do              # aralık/liste, hangisi açık
  nc -z -w 2 <sunucu> $p && echo "$p açık" || echo "$p KAPALI"
done
```

`-w` şart: zaman aşımı vermezsen kapalı portta uzun süre bekler.

**`nc` çıktısını değil çıkış kodunu oku.** Ölçüldü: açık portta
`Ncat: 0 bytes sent, 0 bytes received` yazıyor — "açık" kelimesi geçmiyor.
Kapalıda `Ncat: Connection refused`. Güvenilir sinyal `$?`, bu yüzden
yukarıdaki `&& echo açık || echo KAPALI` kalıbı doğru olan.

**Güvenlik duvarı izni doğrularken yönü karıştırma.** Portun *hedefte* açık
olması yetmez; senin çıkışın da açık olmalı. İki taraftan da dene:

```bash
# istemciden hedefe
nc -zv -w 5 <hedef> <port>
# hedefte dinleyen var mı (hedefte çalıştır)
ss -tlnp | grep <port>
```

`nc` yoksa alternatifler:

```bash
timeout 5 bash -c "</dev/tcp/<sunucu>/<port>" && echo açık || echo kapalı
```

Bash'in kendi özelliği, ek paket gerektirmez; açık ve kapalı portta doğru
sonuç verdiği ölçüldü.

**`curl telnet://` kullanma.** TLS dinleyen açık bir portta `curl: (28)
Time-out` veriyor — port açık olduğu hâlde kapalı sanırsın. Ölçüldü.

Hata mesajını ayırt et:

- **Connection refused** → paket ulaştı, o portta dinleyen yok
- **Connection timed out** → paket düştü; güvenlik duvarı ya da yönlendirme
- **No route to host** → yerel yönlendirme sorunu
- **Name or service not known** → DNS

Bu üç mesaj sorunu üç farklı katmana işaret eder; karıştırma.

TCP bağlantısı kurulup **TLS el sıkışmasında** takılıyorsa katman ağ değil
sertifikadır — `sertifika-tls` becerisine geç.

## Raporlama

Hangi katmanda takıldığını söyle ve kanıtını göster. "Bağlanamıyor" yetmez:
"servis 127.0.0.1'e bağlı, o yüzden uzaktan erişilemiyor — `ss` çıktısı şu"
doğru rapordur.
