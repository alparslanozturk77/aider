---
name: filo-durum-kontrolu
description: Aynı kontrolü birden çok sunucuda çalıştırıp sorunluları ayıklarken kullan. "tüm sunucularda", "filoda", "hepsinde kontrol et", "kaç sunucuda", "toplu", "hangi sunucularda" isteklerinde tetiklenir. Envanter ve playbook ayrıntıları için `ansible`.
---

Doğrulandı: ansible-core 2.16.16, AlmaLinux 10.2 — 2026-08-29

**SSH döngüsü kurma.** `for h in ...; do ssh $h ...; done` kalıbı sırayla
çalışır, tek bir ulaşılamayan sunucuda takılır ve çıktısı ayrıştırılamaz.
Ansible ad-hoc bunu tek komutta, paralel ve makine okunur biçimde yapar.

## 1. Kimi kapsıyorsun — önce bunu gör

```bash
ansible-inventory --graph
ansible <grup> --list-hosts
```

Yanlış envanterle çalıştırılan bir kontrol yanlış sonuç verir; bozuk INI
sessizce boş envanter üretir (bkz. `ansible`).

## 2. Salt-okunur kontrolü çalıştır

```bash
ansible <grup> -m command -a "chronyc tracking" -o
ansible <grup> -m command -a "systemctl is-active splunkforwarder" -o
ansible <grup> -m command -a "df -h /var" -o
```

`-o` her sunucuyu **tek satıra** basar; onlarca sunucunun çıktısını okunur
kılan şey budur. Ölçülen biçim:

```
web01 | CHANGED | rc=0 | (stdout)  20:28:50 up 6 days, load average: 0.00
```

**`-o`'yu yalnızca tek satırlık çıktılarda kullan.** Çok satırlı çıktıda
(`chronyc sources`, `df` tablosu) satır sonları `\n` olarak kaçırılıp tek
satıra sıkışır ve okunmaz hâle gelir — ölçüldü. Çok satırlı çıktı için
`--tree` kullan (aşağıda).

### `CHANGED` seni yanıltmasın

Ölçüldü: `-m command` salt-okunur bir komutta bile **`CHANGED`** yazıyor.
`uptime` çalıştırdın diye hiçbir şey değişmedi. Raporda "34 sunucu
değiştirildi" deme — `command` modülü her zaman böyle davranır.

Gerçekten değişiklik yapıp yapmadığını anlamak için modüle bak, çıktı
etiketine değil.

## 3. Paralellik — varsayılan 5, filo için az

```bash
ansible-config dump | grep DEFAULT_FORKS      # ölçüldü: 5
ansible <grup> -m command -a "uptime" -o -f 20
```

Varsayılan aynı anda **5 sunucu**. Yüzlerce sunuculu bir filoda bu çok
yavaştır. `-f 20` makul bir başlangıç; kontrol düğümünün kaynağına ve ağa
göre artır. Çok yükseltmek kontrol düğümünü boğar.

## 4. Filo envanteri çıkarmak

Hangi sunucu hangi sürümde:

```bash
ansible all -m setup -a "filter=ansible_distribution*" -o
ansible all -m setup -a "filter=ansible_kernel"
```

`setup` modülü salt-okunurdur ve fiilen bir keşif aracıdır: dağıtım, sürüm,
çekirdek, bellek, arayüzler. Ölçülen alanlar arasında
`ansible_distribution: "AlmaLinux"` ve `ansible_distribution_file_path`
bulunuyor.

## 5. Makine okunur çıktı — rapor üretmek için

```bash
ansible <grup> -m command -a "hostname" --tree /tmp/sonuc
ls /tmp/sonuc          # her sunucu için bir JSON dosyası
```

Ölçüldü: her dosya `rc`, `stdout`, `stderr`, `delta` alanlarını içeren tam
bir JSON. CSV ya da HTML rapora çevirmek için `rapor-uret` becerisine geç;
`stdout` alanını ayrıştır, `rc != 0` olanları ayır.

## 6. Sonucu ayıkla — asıl iş bu

Filo kontrolünün değeri "hepsini listelemek" değil, **sapanı bulmaktır**.

```
34 sunucu tarandı, 3 sapma

  db07   unreachable        -> ssh anahtarı ya da isim çözümleme
  web12  rc=127             -> "chronyc: command not found", chrony kurulu değil
  app03  Stratum 16         -> saat kaynağıyla senkron değil

diğer 31: Stratum 2-3, senkron
```

`unreachable` ile `failed`/`rc!=0` farkı teşhisin yönünü belirler: birincisi
sunucuya ulaşılamadı (ağ, ssh, DNS), ikincisi ulaşıldı ama komut düştü.

## Sınır

**Bu beceri salt-okunur tarama içindir.** Filo geneli bir değişiklik
gerekiyorsa (paket kurmak, servis yeniden başlatmak) ad-hoc komutla yapma:
`ansible` becerisine geç, playbook yaz, `--check` ile kuru çalıştır,
`--limit` ile daralt ve kullanıcıdan onay al.

Bir yazma işlemini ad-hoc `-m shell` ile tüm filoya uygulamak, geri alması
en zor hatadır.
