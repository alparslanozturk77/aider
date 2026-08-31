---
name: performans
description: Sunucu yavaşlığı, yüksek yük, CPU/bellek/disk darboğazı ve log analizinde kullan. "yavaş", "yük yüksek", "load average", "cpu", "bellek", "swap", "iowait", "performans", "log", "hata arıyorum" isteklerinde tetiklenir.
---

Darboğazı bulmadan çözüm önerme. Sıra: yük → hangi kaynak → hangi süreç.

## 1. Yük gerçekten yüksek mi

```bash
uptime
nproc
```

Load average'ı **çekirdek sayısına böl.** 4 çekirdekte 4.0 yük %100'dür,
8 çekirdekte aynı sayı %50. Üç sayı 1/5/15 dakikalık ortalamadır: ilki
büyükse sorun yeni başlamış, sonuncusu büyükse süreklidir.

Linux'ta load average yalnızca CPU'yu değil, **kesintisiz uykudaki (D state)
süreçleri de** sayar. Yani yüksek yük çoğu zaman diski ya da NFS'i gösterir,
CPU'yu değil.

## 2. Hangi kaynak

```bash
vmstat 1 5
```

**İlk satırı yok say** — o önyüklemeden beri ortalamadır, anlık durum değil.

| Sütun | Yüksekse |
|---|---|
| `r` | CPU kuyruğu — çekirdek sayısını aşıyorsa CPU darboğazı |
| `b` | Kesintisiz uykudaki süreç — **disk ya da ağ bekliyor** |
| `si`/`so` | Swap giriş/çıkış — bellek yetmiyor, en kötü durum |
| `wa` (CPU) | I/O bekleme — disk darboğazı |
| `id` | Boşta; düşükse CPU dolu |

`si`/`so` sürekli sıfırdan büyükse başka hiçbir şeye bakma, bellek sorunu var.

## 3. CPU

```bash
mpstat -P ALL 1 3         # çekirdek başına; biri %100 diğerleri boşsa tek iş parçacığı
pidstat -u 1 3            # süreç başına
top -b -n1 -o %CPU | head -15
```

`%steal` yüksekse (sanal makinede) sorun sende değil, hipervizörde — komşu
VM'ler CPU'yu yiyor.

## 4. Bellek

```bash
free -h
ps aux --sort=-%mem | head -10
```

**`free` çıktısında `available` sütununa bak, `free` sütununa değil.**
`buff/cache` işletim sisteminin kullandığı ve gerektiğinde bıraktığı alandır;
"bellek dolu" görünmesi normaldir.

OOM killer devreye girdi mi:

```bash
journalctl -k | grep -i "out of memory"
dmesg -T | grep -i oom
```

## 5. Disk

```bash
iostat -x 1 3             # ilk örnek önyüklemeden beri, ATLA
pidstat -d 1 3            # süreç başına G/Ç
```

| Sütun | Anlamı |
|---|---|
| `%util` | Cihazın meşguliyeti; %90+ doymuş |
| `r_await`/`w_await` | Milisaniye cinsinden bekleme. SSD'de >10ms, HDD'de >50ms sorun |
| `aqu-sz` | Kuyruk uzunluğu; sürekli >1 birikme var |

Disk **dolu** mu diye ayrıca bak — dolu disk yavaşlık gibi görünür:
`depolama` becerisine geç.

## 6. Geçmişe bakmak

Sorun geçmişte olduysa `sar` kayıtlarına bak:

```bash
systemctl is-enabled sysstat-collect.timer    # önce toplama açık mı
sar -u -f /var/log/sa/sa$(date +%d -d yesterday)    # CPU, dün
sar -r      # bellek
sar -b      # G/Ç
sar -q      # yük kuyruğu
```

Toplama kapalıysa geçmiş veri **yoktur**; o zaman şimdiden açtır ve bir
sonraki olayda hazır ol.

## 7. Log okuma

```bash
journalctl -p err -b --no-pager | tail -50      # bu önyüklemedeki hatalar
journalctl --since "1 hour ago" -p warning --no-pager
journalctl -u <servis> --since "09:00" --until "09:30" --no-pager
journalctl -k | tail -50                        # çekirdek
```

`-n` ya da `--since` olmadan çalıştırma; log devasa olur ve bağlamı doldurur.
`--no-pager` şart, yoksa komut takılır.

Olay zamanını biliyorsan **zaman aralığıyla daralt** — hata mesajı genelde
belirtiden birkaç saniye öncededir.

Uygulama kendi dosyasına yazıyorsa:

```bash
ls -lt /var/log/ | head
tail -n 200 /var/log/<uygulama>/<dosya>
grep -iE 'error|fail|denied|timeout|refused' /var/log/<dosya> | tail -30
```

SELinux engellemesi performans sorunu gibi görünebilir (yeniden deneme
döngüleri): `ausearch -m avc -ts recent` — `ag-teshis` becerisine bak.

## Raporlama

Darboğazı **sayıyla** göster: "load 8.2, 2 çekirdek, `b` sütunu sürekli 6 —
süreçler diske takılıyor; `%util` %99 ve `w_await` 240ms." Yalnızca "sunucu
yavaş" demek raporlama değildir.

Ölçmediğin şeyi söyleme. Bir hipotezin varsa onu doğrulayan komutu çalıştır.
