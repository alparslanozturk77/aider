---
name: solaris-ldom
description: Solaris 11 sunucu ya da LDOM (Oracle VM Server for SPARC) söz konusuysa kullan. Filo ağırlıkla RHEL olduğu için Linux komutları refleks hâline gelir ve Solaris'te çalışmaz; bu beceri önce işletim sistemini doğrulatır, sonra keşifle ilerletir. "solaris", "sparc", "ldom", "zfs", "zpool", "svcs", "svcadm", "zone", "pkg" isteklerinde tetiklenir.
---

**Bu becerideki hiçbir komut canlı bir Solaris sistemde doğrulanmadı.**
Erişim yok. Bu yüzden burası bir komut referansı değil, **keşif yordamıdır**:
her komutu çalıştırmadan önce sistemin kendi yardımından teyit et.

## Adım 0 — hangi işletim sistemi

Filonun %99'u RHEL. Bu, Linux komutlarını refleksle yazmaya yol açıyor ve
Solaris'te ya hata verir ya da **başka bir şey yapar**. Uzak bir sunucuda ilk
komut her zaman bu olsun:

```bash
uname -s        # Linux | SunOS
uname -a
```

`SunOS` görüyorsan diğer becerilerdeki (`rhel-yonetim`, `ag-teshis`,
`depolama`, `servis-teshis`) komutların çoğu geçersizdir. Buradan devam et.

Sürüm ve donanım:

```bash
cat /etc/release
prtconf -b 2>/dev/null | head
```

## Refleks tuzakları — Linux'ta çalışan, Solaris'te çalışmayan

Bu tabloyu **eşdeğer komut listesi olarak kullanma**; sağ sütun "muhtemelen
buraya bak" demektir, doğrulaman gerekir.

| Linux'ta | Solaris'te muhtemelen | Doğrula |
|---|---|---|
| `systemctl status` | SMF: `svcs`, `svcadm` | `svcs --help` |
| `journalctl -u` | `svcs -xv`, servis log dosyası | `svcs -x` çıktısındaki log yolu |
| `dnf` / `rpm` | IPS: `pkg` | `pkg --help` |
| `df -h`, LVM | ZFS: `zpool`, `zfs list` | `zfs --help` |
| `ip addr`, `ip route` | `ipadm`, `dladm`, `netstat -rn` | `ipadm help` |
| `ss -tlnp` | `netstat -an`, `pfiles` | `netstat --help` |
| `lsof` | `pfiles <pid>`, `fuser` | `pfiles` çıktısı |
| `top` | `prstat` | `prstat --help` |
| `free -m` | `vmstat`, `prtconf | grep Memory` | çıktıyı oku |
| `useradd` | `useradd` (var ama seçenekleri farklı) | `useradd --help` |
| konteyner | zone: `zoneadm list -cv` | `zoneadm help` |

**`man` genelde vardır ve Solaris'te iyi yazılmıştır** — çevrimdışı ortamda
en güvenilir kaynak odur:

```bash
man svcs | head -60
man -s 1m ldm
```

## Keşif yordamı

Bir iş yapman istendiğinde sırayla:

1. `uname -s` ile işletim sistemini doğrula.
2. İlgili aracın var olduğunu gör: `command -v svcs zfs ldm`.
3. Yardımı oku: `<araç> --help` ya da `man <araç>`. **Çıktıyı kullanıcıya
   göster**; ezberden komut kurma.
4. Yalnızca salt-okunur olanı çalıştır, çıktıyı yorumla.
5. Yan etkili bir şey gerekiyorsa komutu **öner**, çalıştırma; onay iste.

Bu yordamı uyguladıktan sonra öğrendiğin doğrulanmış komutu `/hatirla` ile
not al ya da bu beceriye ekle — bir dahakine keşfe gerek kalmasın.

## LDOM (Oracle VM Server for SPARC)

Kontrol alanında (`primary`) `ldm` komutu bulunur. Doğrulanmadı; önce:

```bash
command -v ldm && ldm --help
man -s 1m ldm
```

Salt-okunur görünen alt komutlar `list` ailesidir (`ldm list`,
`ldm list-domain`, `ldm list-bindings` gibi) — ama **hangilerinin var olduğunu
`--help` çıktısından teyit et.**

**Yan etkili ve tehlikeli:** domain durdurma/başlatma, kaynak (CPU/bellek)
ekleme-çıkarma, bağlama (`bind`/`unbind`), yapılandırma kaydetme. Bir LDOM'u
durdurmak üzerinde çalışan tüm servisleri düşürür. Bunları **asla onaysız
çalıştırma**; komutu göster, gerekçesini yaz, kullanıcı çalıştırsın.

Kontrol alanının kendisine müdahale tüm konuk alanları etkiler — orada
değişiklik önerirken bunu açıkça söyle.

## ZFS — Linux LVM refleksiyle yaklaşma

Disk büyütme, `disk-ekleme` becerisindeki LVM/XFS yordamıyla **aynı değildir**.
ZFS'te havuz ve dosya sistemi ayrı kavramlar, `xfs_growfs` karşılığı yok.

Salt-okunur bakış:

```bash
zpool list
zpool status
zfs list
zfs get quota,reservation,used,available <havuz/fs>
```

Havuza disk eklemek, `quota` değiştirmek, snapshot silmek yan etkilidir.
**`zpool add` ile `zpool attach` farklıdır** ve yanlış olanı seçmek havuzun
yapısını geri alınamaz biçimde değiştirir — bu komutları önerirken farkı
`man zpool`'dan teyit et ve kullanıcıya sor.

## Raporlama

Solaris'ten dönen çıktıyı Linux terimlerine çevirirken dikkatli ol. Bir
kavramın karşılığından emin değilsen "Solaris'te bunun karşılığı X'tir" deme;
çıktıyı göster ve neyi ölçtüğünü söyle.

Doğrulanmamış bir komutu çalıştırdıysan raporda bunu belirt.
