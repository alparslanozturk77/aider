---
name: nfs-mount
description: NFS paylaşımı mount ederken ya da asılı NFS mount teşhis ederken kullan. "nfs", "mount", "showmount", "paylaşım", "df takıldı", "nfs yanıt vermiyor", "_netdev", "hard mount" isteklerinde tetiklenir. Yerel disk ve LVM için `disk-ekleme`.
---

Doğrulandı: AlmaLinux 10.2 — 2026-08-29 (showmount, rpcinfo, nfsstat, findmnt mevcut)

## Önce sunucu ne paylaşıyor

```bash
showmount -e <nfs-sunucu>            # dışa açılan paylaşımlar
rpcinfo -p <nfs-sunucu> | grep nfs   # NFS servisi ayakta mı
```

`showmount` yanıt vermiyorsa sorun mount seçeneklerinde değil erişimde:
2049/tcp (ve NFSv3 ise 111/tcp rpcbind) açık mı — `ag-teshis` becerisine geç.

## Geçici mount — önce bunu dene

```bash
mount -t nfs <sunucu>:/paylasim /mnt/test
findmnt /mnt/test
umount /mnt/test
```

Kalıcı hâle getirmeden önce geçici mount'un çalıştığını gör. fstab'a yazılan
bozuk bir satır makineyi açılmaz hâle getirir.

## Kalıcı — fstab satırı

```
<sunucu>:/paylasim  /mnt/veri  nfs  defaults,_netdev,soft,timeo=100,retrans=3  0 0
```

| Seçenek | Neden |
|---|---|
| `_netdev` | Ağ hazır olmadan mount denenmesin; olmazsa açılış takılır |
| `soft` | Sunucu yanıt vermezse hata dön. `hard` (varsayılan) sonsuza dek bekler |
| `timeo`/`retrans` | Ne kadar bekleyip kaç kez deneyeceği |
| `noauto` | Açılışta mount etme, elle |

Yazdıktan sonra **yeniden başlatmadan** doğrula:

```bash
mount -a                             # hata vermemeli
systemctl daemon-reload
findmnt /mnt/veri
```

## `hard` mount asılması — en sık görülen NFS olayı

Sunucu düşer; istemcideki her `df` ve `ls` sonsuza dek bekler, süreçler
`D` state'e girer ve **`kill -9` bile çalışmaz**. Bu yüzden kritik olmayan
paylaşımlarda `soft` tercih edilir.

Teşhis ederken **`df` kullanma** — o da asılır. Asılmayan komutlar:

```bash
findmnt -t nfs,nfs4                  # hangi NFS mount'lar var
cat /proc/self/mountinfo | grep nfs
nfsstat -c | head -20                # retrans yüksekse sorun ağda
dmesg -T | grep -i "nfs.*not responding"
```

`dmesg` içindeki `nfs: server X not responding, still trying` satırı `hard`
mount'un beklediğini gösterir; `timed out` ise `soft` mount'un vazgeçtiğini.

## Kurtarma

Sunucu geri geldiğinde çoğu zaman kendiliğinden çözülür. Gelmiyorsa:

```bash
umount -f /mnt/veri                  # zorla
umount -l /mnt/veri                  # lazy: ağaçtan ayır
```

`-l` mount'u ağaçtan ayırır ama **açık dosya tanıtıcısı olan süreçler yine
takılı kalır**; kesin çözüm çoğu zaman yeniden başlatmadır. Yan etkilidir,
üzerinde çalışan servisleri düşürür — onay al.

## Raporlama

Hangi sunucunun hangi paylaşımını nereye mount ettiğini, seçenekleri ve
`findmnt` çıktısını göster. Asılma teşhisinde hangi komutun asıldığını ve
hangisinin yanıt verdiğini yaz — ayrım teşhisin kendisidir.
