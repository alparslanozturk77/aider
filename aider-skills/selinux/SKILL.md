---
name: selinux
description: SELinux'un bir şeyi engellediğinden şüphelendiğinde kullan. Mod tespiti, AVC okuma, boolean, port etiketi, dosya bağlamı. "selinux", "avc", "denied", "permission denied ama izinler doğru", "setsebool", "semanage", "restorecon", "context" isteklerinde tetiklenir.
---

Doğrulandı: AlmaLinux 10.2, targeted politika — 2026-08-29

## Adım 0 — mod ne? Bunu atlarsan yanlış yola girersin

```bash
sestatus
```

`getenforce` tek kelime döndürür ama `sestatus` iki ayrı bilgiyi verir ve
ikisi farklı olabilir:

```
Current mode:                   permissive
Mode from config file:          permissive
```

- **Permissive** ise SELinux hiçbir şeyi engellemiyor, yalnızca kaydediyor.
  Sorun devam ediyorsa **suçlu SELinux değildir** — başka katmana bak.
- `Current mode` ile `Mode from config file` farklıysa biri `setenforce`
  çalıştırmış demektir; yeniden başlatmada geri döner. Bunu rapor et.

## Adım 1 — gerçekten engelledi mi

```bash
ausearch -m avc -ts recent
ausearch -m avc -ts today
```

Kayıt yoksa `<no matches>` döner — ölçüldü. Bu, SELinux'un o işlemi
engellemediği anlamına gelir.

`auditd` çalışmıyorsa AVC hiç yazılmaz; önce `systemctl is-active auditd`.

AVC satırında bakılacaklar: `scontext` (kaynak alan), `tcontext` (hedef
etiket), `tclass` (dosya mı port mu soket mi), `denied { ... }` (hangi izin).
Bu dördü hangi düzeltmenin gerektiğini söyler.

## Adım 2 — hangi tür sorun

| AVC ipucu | Sorun | Çözüm |
|---|---|---|
| `tclass=tcp_socket`, `name_connect` | Servis dışarı bağlanamıyor | boolean |
| `tclass=tcp_socket`, `name_bind` | Standart dışı portta dinleyemiyor | `semanage port` |
| `tclass=file`, `read`/`open` | Dosya etiketi yanlış | `restorecon` / `semanage fcontext` |

## Boolean

```bash
getsebool -a | grep <servis>          # 365 boolean var, daralt
getsebool httpd_can_network_connect
setsebool -P httpd_can_network_connect on     # YAN ETKİLİ, ONAY AL
```

`-P` olmadan yapılan değişiklik yeniden başlatmada kaybolur. Kalıcı istemiyorsan
bile test ederken bunu bil.

Sık gerekenler: `httpd_can_network_connect` (reverse proxy),
`httpd_can_network_connect_db`, `httpd_use_nfs`.

## Port etiketi

Servis standart dışı bir portta dinleyemiyorsa sebep neredeyse her zaman bu.
Ölçülen gerçek çıktı:

```bash
semanage port -l | grep ^http_port_t
http_port_t    tcp    80, 81, 443, 488, 8008, 8009, 8443, 9000
```

Listede **8080 yok** — nginx'i 8080'e alırsan `name_bind` reddi alırsın.

```bash
semanage port -a -t http_port_t -p tcp 8080   # YAN ETKİLİ, ONAY AL
semanage port -m -t http_port_t -p tcp 8080   # zaten tanımlıysa -a değil -m
```

Port başka bir tipe atanmışsa `-a` hata verir; o zaman `-m` gerekir.

## Dosya bağlamı

```bash
ls -Zd <yol>                          # mevcut etiket
matchpathcon <yol>                    # olması gereken etiket
```

İkisi farklıysa etiket bozulmuştur (genelde `mv` ile taşımaktan; `cp`
hedefin etiketini alır, `mv` kaynağınkini taşır).

```bash
restorecon -Rv <yol>                                    # politikaya göre düzelt
semanage fcontext -a -t httpd_sys_content_t '<yol>(/.*)?'   # YAN ETKİLİ
restorecon -Rv <yol>                                    # sonra uygula
```

`semanage fcontext` kuralı yazar, `restorecon` uygular. İkisi de gerekir —
yalnız birincisini çalıştırmak hiçbir şeyi değiştirmez.

## audit2allow — son çare

```bash
ausearch -m avc -ts recent | audit2allow -m yerel_politika
```

Ürettiği politikayı **okumadan yükleme**. Çoğu zaman doğru cevap bir boolean
ya da doğru etikettir; özel politika modülü teknik borçtur ve yükseltmelerde
sorun çıkarır. Yüklemek yan etkilidir, onay al.

`sealert` minimal kurulumda yok (ölçüldü) — `setroubleshoot-server` paketi
gerekir, kurmadan önce sor.

## Değişmez kural

**SELinux'u devre dışı bırakma.** `setenforce 0` teşhis için geçici olarak
denenebilir ama açık bırakılmaz; `/etc/selinux/config` ile kalıcı kapatmak
banka ortamında CIS denetimine takılır. Doğru çözüm boolean, port etiketi ya
da dosya bağlamıdır — hepsi denetlenebilir ve gerekçelendirilebilir.
