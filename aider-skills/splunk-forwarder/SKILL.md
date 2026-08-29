---
name: splunk-forwarder
description: Splunk Universal Forwarder takıldığında, log göndermeyi durdurduğunda ya da servisi yanıt vermediğinde kullan. "splunk", "splunkforwarder", "forwarder", "log gitmiyor", "splunkd", "log akmıyor" isteklerinde tetiklenir.
---

Bilinen tekrarlayan olay: **forwarder servisi takılıyor.** Süreç ayakta
görünür ama log akmaz — bu yüzden `systemctl is-active` tek başına yeterli
değildir.

> Yollar ve komutlar kurulum biçimine göre değişir. Aşağıdakiler tipik
> paket kurulumu içindir; ilk kez bir sunucuda çalışıyorsan 1. adımla
> gerçek yolu bul.

## 1. Nerede kurulu, nasıl yönetiliyor

```bash
ls -d /opt/splunkforwarder /opt/splunk 2>/dev/null
systemctl list-unit-files | grep -i splunk
rpm -qa | grep -i splunk
```

Servis adı kurulumdan kuruluma değişir: `SplunkForwarder.service`,
`splunk.service` ya da eski init betiği olabilir. Bulduğun adı kullan,
varsayma.

CLI genelde: `/opt/splunkforwarder/bin/splunk`

## 2. Gerçekten çalışıyor mu

```bash
systemctl status <splunk-servis> --no-pager
/opt/splunkforwarder/bin/splunk status
ps -ef | grep -c '[s]plunkd'
```

`systemctl` "active" derken `splunk status` "not running" diyebilir — süreç
var ama splunkd içeride ölmüştür. **İkisini birden kontrol et.**

## 3. Asıl soru: log akıyor mu

Servisin ayakta olması bir şey ifade etmez. Çıkışı kontrol et:

```bash
/opt/splunkforwarder/bin/splunk list forward-server
```

`Active forwards` altında indexer görünmeli. `Configured but inactive`
altındaysa bağlantı kurulamıyordur.

Ağ tarafı:

```bash
ss -tnp | grep splunkd                    # kurulu bağlantı var mı
nc -zv -w 5 <indexer> 9997                # port açık mı (varsayılan 9997)
```

Bağlantı yoksa sorun forwarder'da değil ağda ya da güvenlik duvarındadır —
FW ekibine gitmeden önce `ag-teshis` becerisiyle doğrula.

## 4. Kuyruklar tıkalı mı — "takılma"nın asıl göstergesi

Forwarder gönderemezse iç kuyrukları dolar ve sonunda okumayı da durdurur.
Belirti tam olarak budur: süreç ayakta, hiçbir şey akmıyor.

```bash
grep -i "blocked" /opt/splunkforwarder/var/log/splunk/splunkd.log | tail -20
tail -50 /opt/splunkforwarder/var/log/splunk/metrics.log | grep -i queue
```

`blocked=true` satırları hangi kuyruğun dolduğunu gösterir
(`parsingQueue`, `aggQueue`, `typingQueue`, `indexQueue`, `tcpout`).
`tcpout` tıkalıysa indexer'a ulaşılamıyordur.

## 5. Log ve disk

```bash
tail -100 /opt/splunkforwarder/var/log/splunk/splunkd.log
df -h /opt/splunkforwarder
du -sh /opt/splunkforwarder/var/lib/splunk 2>/dev/null
```

Gönderilemeyen veri diskte birikir. `/opt` dolarsa forwarder durur **ve**
sunucudaki başka şeyler de etkilenir — `depolama` becerisine geç.

İzlenen dosyalar ve nerede kaldığı:

```bash
/opt/splunkforwarder/bin/splunk list monitor
/opt/splunkforwarder/bin/splunk list inputstatus
```

`inputstatus`, her dosyanın ne kadarının okunduğunu gösterir. Bir dosyada
takılı kalmışsa (`file position` ilerlemiyorsa) sorun o dosyadadır — çok
büyük ya da izin sorunlu olabilir.

## 6. Yeniden başlatma

Yan etkili, **onay al**. Yeniden başlatma sırasında log toplanmaz; kuyruktaki
veri korunur ama gecikme olur.

```bash
sudo systemctl restart <splunk-servis>
# ya da
sudo /opt/splunkforwarder/bin/splunk restart
```

Sonrasında doğrula — yalnızca "başladı" demek yetmez:

```bash
/opt/splunkforwarder/bin/splunk status
/opt/splunkforwarder/bin/splunk list forward-server
grep -i blocked /opt/splunkforwarder/var/log/splunk/splunkd.log | tail -5
```

`Active forwards` altında indexer görünüyorsa düzelmiştir.

## 7. Tekrarlıyorsa

Sürekli yeniden başlatmak gerekiyorsa sebep forwarder'da olmayabilir:

- **Indexer tarafı doluysa** forwarder'ı bloklar. Splunk ekibine sor.
- **Ağ kararsızsa** bağlantı sürekli kopar; `splunkd.log` içinde
  `connection reset` / `timeout` say.
- **Disk doluyorsa** kuyruk yazamaz.
- **Sertifika süresi dolduysa** (SSL forwarding kullanılıyorsa) bağlantı
  sessizce reddedilir.

Bulguyu `Hatirla` ile kaydet: hangi sunucu, ne sıklıkla, hangi kuyruk tıkalıydı.
Desen sebebi gösterir.

## Uzak sunucuda

```
Ssh(host="<sunucu>", command="systemctl is-active <splunk-servis>; /opt/splunkforwarder/bin/splunk status")
Ssh(host="<sunucu>", command="/opt/splunkforwarder/bin/splunk list forward-server")
```

Birden fazla sunucuda aynı sorun varsa `filo-durum-kontrolu` becerisine geç.

## Raporlama

"Servis çalışıyor" yeterli değil. Şunları söyle: `splunk status` ne dedi,
`list forward-server` indexer'ı aktif gösteriyor mu, kuyruklarda `blocked`
var mıydı. Yeniden başlattıysan kaçıncı kez olduğunu da yaz.
