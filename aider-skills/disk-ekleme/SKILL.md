---
name: disk-ekleme
description: Disk eklerken, LVM birimi büyütürken ya da NFS paylaşımı mount ederken kullan. "disk ekle", "lvm", "pvcreate", "vgextend", "lvextend", "xfs_growfs", "büyüt", "yer aç", "nfs", "mount", "fstab" isteklerinde tetiklenir.
---

Buradaki her adım yan etkilidir ve bir kısmı geri alınamaz. Disk **dolduğu**
için buradaysan önce `depolama` becerisiyle teşhis yap — bazen alan açmak
disk eklemekten hızlıdır.

## Yeni disk ekleme (LVM + XFS)

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

## NFS mount

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

## Raporlama

Hangi cihazı hangi VG'ye kattığını, yeni boyutu ve fstab satırını göster.
`df -h` çıktısını öncesi/sonrası ver.

Geri alınamaz bir adım attıysan (XFS büyütme, bölüm tablosu değişikliği)
bunu açıkça söyle.
