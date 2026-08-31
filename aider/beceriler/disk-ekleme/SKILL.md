---
name: disk-ekleme
description: Disk eklerken, bölüm ya da LVM birimi büyütürken kullan. "disk ekle", "lvm", "pvcreate", "vgextend", "lvextend", "xfs_growfs", "growpart", "büyüt", "yer aç", "disk göründü mü" isteklerinde tetiklenir. NFS paylaşımı için `nfs-mount`, disk dolduğu için buradaysan önce `depolama`.
---

Doğrulandı: AlmaLinux 10.2 — 2026-08-29

Buradaki her adım yan etkilidir ve bir kısmı geri alınamaz. **Yanlış diske
yazmak veri kaybıdır** — hangi cihaz olduğunu iki kez doğrula.

## Adım 0 — LVM var mı? İki tamamen farklı yol var

```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT
pvs
```

**`pvs` boş dönerse LVM YOKTUR** ve `pvcreate`/`vgextend`/`lvextend` yolu
geçersizdir. Dikkat: ölçüldü, LVM kurulu olmayan bir makinede `pvs` hata
vermiyor — çıkış kodu 0, çıktı sıfır satır. "Komut çalıştı, sorun yok"
sanma; satır yoksa LVM yok demektir.

| Durum | Yol |
|---|---|
| `pvs` PV listeliyor | LVM yolu (aşağıda) |
| `pvs` boş, `lsblk` doğrudan bölüm gösteriyor | Düz bölüm yolu (aşağıda) |

Ölçülen düz bölüm örneği — `/` doğrudan `sda4` üzerinde, LVM yok:

```
sda      64G disk
├─sda3    1G part xfs    /boot
└─sda4 62.8G part xfs    /
```

## Disk görünmüyorsa: SCSI taraması

Sanallaştırma ekibi çalışan bir VM'e disk eklediğinde çekirdek onu
kendiliğinden görmeyebilir. Bu adım atlanınca "eklediler ama yok" sanılır.
Tarama salt-okunurdur, veri riski yoktur.

```bash
for h in /sys/class/scsi_host/host*/scan; do echo "- - -" > "$h"; done
lsblk                                        # şimdi göründü mü
rescan-scsi-bus.sh                           # sg3_utils kuruluysa
```

**Var olan disk büyütüldüyse** (yeni disk eklenmediyse) taranacak olan
cihazın kendisidir:

```bash
echo 1 > /sys/class/block/sda/device/rescan
lsblk /dev/sda                               # yeni boyut göründü mü
```

## Yol A — LVM

Yeni disk `/dev/sdb`, hedef `/dev/vg0/lv_var`:

```bash
pvcreate /dev/sdb                        # PV olarak işaretle
vgextend vg0 /dev/sdb                    # VG'ye kat
vgs                                      # VFree arttı mı, DOĞRULA
lvextend -l +100%FREE /dev/vg0/lv_var    # ya da -L +50G
xfs_growfs /var                          # MOUNT NOKTASI, cihaz değil
df -h /var
```

`ext4` ise son iki adım: `resize2fs /dev/vg0/lv_var` (bu **cihaz** alır).

Sıfırdan yeni birim:

```bash
pvcreate /dev/sdb
vgcreate vg_veri /dev/sdb
lvcreate -l 100%FREE -n lv_veri vg_veri
mkfs.xfs /dev/vg_veri/lv_veri
```

## Yol B — LVM yok, bölüm büyütme

Disk büyütüldü ama bölüm eski boyutta kaldı. Sıra: bölüm tablosu → dosya
sistemi.

```bash
parted -s /dev/sda print                 # salt-okunur, mevcut durumu gör
growpart /dev/sda 4                      # DİKKAT: disk ve bölüm AYRI argüman
xfs_growfs /                             # mount noktası
df -h /
```

`growpart /dev/sda4` **yanlıştır**; komut `growpart <disk> <bölüm-no>` alır.

Bölüm tablosu değişikliği geri alınamaz. Öncesinde `parted print` çıktısını
kullanıcıya göster ve onay al.

## İki kalıcı tuzak

- **`xfs_growfs` mount noktası alır, `resize2fs` cihaz alır.** Karıştırmak
  sık yapılan hatadır.
- **XFS küçültülemez.** Yalnızca büyür. Yanlış boyutta oluşturduysan tek yol
  yedekleyip yeniden oluşturmaktır.

## fstab — atlanırsa yeniden başlatmada kaybolur

**UUID kullan, cihaz adı kullanma.** `/dev/sdb` yeniden başlatmada `/dev/sdc`
olabilir ve sistem açılmaz.

```bash
blkid /dev/vg_veri/lv_veri               # UUID'yi al
echo 'UUID=<uuid>  /veri  xfs  defaults  0 0' >> /etc/fstab
```

Yazdıktan sonra **yeniden başlatmadan** doğrula — bozuk fstab makineyi
açılmaz hâle getirir:

```bash
mount -a                                 # hata vermemeli
systemctl daemon-reload
findmnt /veri
```

`mount -a` hata verirse satırı düzelt. Bu kontrolü atlayıp yeniden başlatmak
kurtarma moduna düşmek demektir.

## Durum kontrolü

```bash
pvs -o +pv_used                          # PV'ler ve kullanım
vgs -o +vg_free                          # VG'lerde boş alan
lvs -o +devices                          # LV'ler hangi diskte
xfs_info /veri                           # blok boyutu, günlük
findmnt /veri -o SOURCE,FSTYPE,OPTIONS
```

## Raporlama

Hangi cihazı hangi VG'ye kattığını ya da hangi bölümü büyüttüğünü, yeni
boyutu ve fstab satırını göster. `df -h` çıktısını öncesi/sonrası ver.

Geri alınamaz bir adım attıysan (bölüm tablosu değişikliği, XFS büyütme)
bunu açıkça söyle.
