---
name: depolama
description: Disk dolması, LVM, mount ve dosya sistemi sorunlarında kullan. "disk dolu", "yer kalmadı", "no space", "lvm", "mount", "partition", "inode", "nfs" isteklerinde tetiklenir.
---

Disk dolması bir numaralı olaydır ve iki tuzağı vardır: inode ayrı dolar,
silinen dosya yer açmayabilir.

## 1. Genel tablo

```bash
df -h                # blok kullanımı
df -i                # inode kullanımı — AYRI DOLAR
```

`df -h` %40 gösterirken `df -i` %100 olabilir. O durumda "disk dolu" hatası
alırsın ama yer vardır; sorun dosya *sayısı*dır. Genelde küçük dosya üreten
bir dizin (oturum dosyaları, mail kuyruğu, cache) suçludur.

## 2. Yeri kim yiyor

```bash
du -xh --max-depth=1 / 2>/dev/null | sort -rh | head -15
du -xh --max-depth=1 /var 2>/dev/null | sort -rh | head -15
```

`-x` şart: dosya sistemi sınırında dursun, yoksa NFS ve bind mount'lara dalıp
saatlerce sürer ve yanlış sayı verir.

En sık suçlular: `/var/log`, `/var/lib/docker`, `/var/lib/containers`,
`/var/cache`, kullanıcı ev dizinleri, uygulamanın kendi log dizini.

## 3. Silinmiş ama açık tutulan dosyalar

`df` doluyu, `du` boşu gösteriyorsa sebep budur: bir süreç silinmiş bir
dosyayı hâlâ açık tutuyor, alan ancak süreç kapanınca serbest kalır.

```bash
lsof +L1 2>/dev/null | head -20
```

**`lsof` minimal RHEL/AlmaLinux kurulumlarında YOKTUR** (doğrulandı: AlmaLinux
10.2). Kurmadan, `/proc` üzerinden aynı bilgiye ulaşılır:

```bash
ls -l /proc/*/fd 2>/dev/null | grep deleted
```

Hangi sürecin tuttuğunu bulmak için PID'i yoldan oku:

```bash
for p in /proc/[0-9]*; do
  ls -l $p/fd 2>/dev/null | grep -q deleted && echo "$p $(cat $p/comm)"
done

Çözüm: ilgili servisi yeniden başlat (yan etkili, **onay al**). Genelde
suçlu, log dosyası döndürülmüş ama yeniden başlatılmamış bir servistir.

## 4. Log şişmesi

```bash
journalctl --disk-usage
du -sh /var/log/* | sort -rh | head
```

Yan etkili, onay al:

```bash
journalctl --vacuum-time=7d
journalctl --vacuum-size=500M
```

Tekrarlıyorsa `/etc/systemd/journald.conf` içinde `SystemMaxUse` ayarla ve
`logrotate` yapılandırmasına bak. Kalıcı çözüm budur; elle temizlemek
belirtiyi bastırır.

## 5. Container katmanı

```bash
docker system df
podman system df
```

`/var/lib/docker` şişmişse önce ne olduğuna bak. `docker system prune`
kullanılmayan **volume'ları da** silebilir — veri kaybı riski, onaysız
çalıştırma. Güvenli sıra: önce `-a` olmadan imaj temizliği, volume'lara en son
ve ancak sahibiyle konuşup dokun.

## 6. LVM ile büyütme

```bash
lsblk
pvs ; vgs ; lvs
vgdisplay <vg> | grep Free
```

Boş alan varsa (yan etkili, **onay al**, önce yedek doğrula):

```bash
lvextend -L +10G /dev/<vg>/<lv>
xfs_growfs /mount/noktasi        # XFS
resize2fs /dev/<vg>/<lv>         # ext4
```

XFS **küçültülemez**, yalnızca büyütülür. Bu geri alınamaz bir yön, karar
verirken bunu hesaba kat.

## 7. Yeni disk ekleme (LVM + XFS)

Sık yaptığın iş. Sıra önemli; bir adım atlanırsa yeniden başlatmada mount
kaybolur ya da veri erişilemez olur.

**Her adım yan etkilidir. Yanlış diske yazmak veri kaybıdır — önce hangi
cihaz olduğunu iki kez doğrula.**

```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT   # yeni disk hangisi
lsblk -f                                     # üzerinde dosya sistemi var mı
```

Yeni diskte `FSTYPE` ve `MOUNTPOINT` **boş** olmalı. Doluysa o disk
kullanımdadır — devam etme, kullanıcıya sor.

### Disk görünmüyorsa: SCSI taraması

Sanallaştırma ekibi çalışan bir VM'e disk eklediğinde çekirdek onu
kendiliğinden görmeyebilir. `lsblk` yeni diski göstermiyorsa taratmak
gerekir — bu adım atlanınca "eklediler ama yok" sanılır:

```bash
for h in /sys/class/scsi_host/host*/scan; do echo "- - -" > "$h"; done
lsblk                                        # şimdi göründü mü
```

Ya da `sg3_utils` kuruluysa (doğrulandı: AlmaLinux 10.2'de var):

```bash
rescan-scsi-bus.sh
```

**Var olan bir disk büyütüldüyse** (yeni disk eklenmediyse), taranacak olan
cihazın kendisidir:

```bash
echo 1 > /sys/class/block/sda/device/rescan
lsblk /dev/sda                               # yeni boyut göründü mü
```

Bu durumda bölüm tablosu da büyütülmeli (`growpart` ya da `parted`), sonra
`pvresize /dev/sda4` ile PV yeni alanı görür. Yeni disk eklemekten farklı bir
akıştır, karıştırma.

Tarama salt-okunurdur, veri riski yoktur.

### Var olan LV'yi büyütmek (en sık durum)

Yeni disk `/dev/sdb`, hedef `/dev/vg0/lv_var`:

```bash
pvcreate /dev/sdb                    # PV olarak işaretle
vgextend vg0 /dev/sdb                # VG'ye kat
vgs                                  # VFree arttı mı, doğrula
lvextend -l +100%FREE /dev/vg0/lv_var    # ya da -L +50G
xfs_growfs /var                      # MOUNT NOKTASI, cihaz değil
df -h /var                           # doğrula
```

İki tuzak:

- **`xfs_growfs` mount noktası alır**, blok cihazı değil. `resize2fs` ise
  cihaz alır. İkisini karıştırmak sık yapılan hatadır.
- **XFS küçültülemez.** Yalnızca büyür. Yanlış boyutta oluşturduysan tek yol
  yedekleyip yeniden oluşturmaktır. Karar geri alınamaz.

`ext4` için son iki adım: `resize2fs /dev/vg0/lv_var`

### Sıfırdan yeni bir birim

```bash
pvcreate /dev/sdb
vgcreate vg_veri /dev/sdb
lvcreate -l 100%FREE -n lv_veri vg_veri
mkfs.xfs /dev/vg_veri/lv_veri
mkdir -p /veri
```

### fstab — atlanırsa yeniden başlatmada kaybolur

**UUID kullan, cihaz adı kullanma.** `/dev/sdb` yeniden başlatmada `/dev/sdc`
olabilir ve sistem açılmaz.

```bash
blkid /dev/vg_veri/lv_veri           # UUID'yi al
echo 'UUID=<uuid>  /veri  xfs  defaults  0 0' >> /etc/fstab
```

Yazdıktan sonra **yeniden başlatmadan** doğrula — bozuk fstab makineyi
açılmaz hâle getirir:

```bash
mount -a                             # hata vermemeli
systemctl daemon-reload
findmnt /veri
```

`mount -a` hata verirse fstab satırını düzelt. Bu kontrolü atlayıp yeniden
başlatmak, kurtarma moduna düşmek demektir.

### Durum kontrolü

```bash
pvs -o +pv_used                      # PV'ler ve kullanım
vgs -o +vg_free                      # VG'lerde boş alan
lvs -o +devices                      # LV'ler hangi diskte
xfs_info /veri                       # blok boyutu, günlük
```

## 8. NFS mount

```bash
showmount -e <nfs-sunucu>            # sunucu ne paylaşıyor
rpcinfo -p <nfs-sunucu> | grep nfs   # NFS servisi ayakta mı
```

Geçici mount (test için):

```bash
mount -t nfs <sunucu>:/paylasim /mnt/test
```

Kalıcı — fstab satırı:

```
<sunucu>:/paylasim  /mnt/veri  nfs  defaults,_netdev,soft,timeo=100,retrans=3  0 0
```

Seçeneklerin anlamı, ve neden önemli:

| Seçenek | Neden |
|---|---|
| `_netdev` | Ağ hazır olmadan mount denenmesin; olmazsa açılış takılır |
| `soft` | Sunucu yanıt vermezse hata dön. `hard` (varsayılan) sonsuza dek bekler |
| `timeo`/`retrans` | Ne kadar bekleyip kaç kez deneyeceği |
| `noauto` | Açılışta mount etme, elle |

**`hard` mount'un asılması en sık görülen NFS olayıdır:** sunucu düşer,
istemcideki her `df` ve `ls` sonsuza dek bekler, süreçler D state'e girer ve
`kill -9` bile çalışmaz. Bu yüzden kritik olmayan paylaşımlarda `soft`
tercih edilir.

Asılı NFS teşhisi — `df` de asılacağı için onu kullanma:

```bash
findmnt -t nfs,nfs4                  # hangi NFS mount'lar var
cat /proc/self/mountinfo | grep nfs
nfsstat -c | head -20                # istemci istatistikleri, retrans yüksekse sorun
dmesg -T | grep -i "nfs.*not responding"
```

Kurtarma: sunucu geri geldiğinde kendiliğinden çözülür. Gelmiyorsa
`umount -f -l /mnt/veri` (lazy) mount'u ağaçtan ayırır ama süreçler yine de
takılı kalabilir — kesin çözüm çoğu zaman yeniden başlatmadır.

## 9. Mount sorunları

```bash
findmnt
mount | grep -i " ro,"           # salt-okunur geçmiş dosya sistemleri
dmesg | tail -30                 # G/Ç hataları
cat /etc/fstab
```

Dosya sistemi kendini salt-okunur yaptıysa neredeyse her zaman donanım ya da
G/Ç hatası vardır. `dmesg`'e bakmadan yeniden mount etme.

NFS asılı kaldıysa `df` de asılır. `findmnt` ile hangi mount'un sorunlu
olduğunu bul, `df` ile aramaya çalışma.

## Raporlama

Sayıyı ve nedeni birlikte ver: "`/var` %98 dolu, `/var/log/app` 40 GB, en
büyük dosya 12 GB'lık `app.log` — logrotate yapılandırılmamış." Yalnızca
"disk dolu" demek raporlama değildir.

Temizlik önerirken hangisinin geri alınamaz olduğunu ayrıca belirt.
