---
name: sistem-guncelleme
description: RHEL ailesinde paket güncellemesi, güvenlik yaması ve yeniden başlatma kararı için kullan. "güncelle", "güncel mi", "update", "upgrade", "yama", "dnf update", "güvenlik yaması", "reboot gerekiyor mu" isteklerinde tetiklenir. Devralma ve teslim akışı için `sunucu-teslim`.
---

Doğrulandı: AlmaLinux 10.2, dnf 4.20.0 — 2026-08-29

**Paket yöneticisi `dnf`.** `apt` Debian/Ubuntu'ya aittir, RHEL ailesinde
yoktur — `command not found` alırsın. `yum` çalışır ama `dnf-3`'e sembolik
bağdır (ölçüldü), yeni yazılan komutlarda `dnf` kullan.

Salt-okunur:

```bash
dnf check-update                      # ne güncellenecek
dnf updateinfo summary                # kaç güvenlik bildirimi var
dnf updateinfo list --security        # hangileri
dnf update --security --assumeno      # kuru çalıştırma, hiçbir şey yapmaz
```

Yan etkili (**onay al**):

```bash
dnf -y upgrade
needs-restarting -r                   # yeniden başlatma gerekiyor mu
```

`needs-restarting -r` **çıkış kodu 1 dönerse** yeniden başlatma gerekir
(ölçüldü; çıktıyı borulama, çıkış kodunu oku). Yeniden başlatma yan
etkilidir ve izin sisteminde onaya takılır — özel olarak istenmedikçe yapma.

### En sık yanlış okuma

`updateinfo list --security` güvenlik yaması listeliyor ama
`dnf update --security` "No security updates needed" diyorsa, **yama zaten
kuruludur ve makine hâlâ eski çekirdekle çalışıyordur.** Ölçülen örnek:

```
Security: kernel-core-...-211.49.1 is an installed security update
Security: kernel-core-...-211.47.1 is the currently running version
```

Bu durumda gereken şey güncelleme değil **yeniden başlatmadır**. Paket
kurmaya çalışmak hiçbir şey değiştirmez. `needs-restarting -r` ile teyit et.

Devralma ve teslim akışının tamamı için `sunucu-teslim` becerisine geç.


## Satellite ile yönetilen sunucuda

Depolar Satellite'tan gelir; `dnf repolist` boşsa ya da beklenmedikse sorun
güncellemede değil abonelik/içerik görünümündedir — `satellite-yonetim`
becerisine geç. Yeni bir sunucuyu abone edip güncelleyip teslim etme akışı
`sunucu-teslim`'de.

```bash
dnf repolist                          # hangi depolar etkin
subscription-manager status           # YALNIZCA RHEL, AlmaLinux/Rocky'de yok
```

## Filoda güncellik taraması

Tek sunucu değil "hangileri güncel değil" sorusuysa `filo-durum-kontrolu`
becerisine geç; ad-hoc olarak:

```bash
ansible <grup> -m command -a "needs-restarting -r" -o
```

`-o` tek satırlık çıktı için uygundur. Yeniden başlatma gereken sunucuları
bu şekilde tek taramada ayırabilirsin.

## Yapma

- Kullanıcı istemediyse **yeniden başlatma.** Güncelleme sonrası reboot
  gerekse bile kararı kullanıcı verir; sen `needs-restarting -r` sonucunu
  raporlarsın.
- `dnf -y upgrade`'i onaysız çalıştırma. Banka ortamında paket güncellemesi
  değişiklik kaydı gerektirebilir.
- Çekirdek güncellemesinden sonra eski çekirdeği silme (`dnf remove kernel`)
  — geri dönüş yolunu kapatır.
