---
name: filo-durum-kontrolu
description: Birden çok sunucuda durum sorgulaman istendiğinde kullan — NTP/saat, disk, servis, yama, uptime. "tüm sunucularda", "filoda", "bütün makinelerde", "ntp kontrol et", "chrony", "disk doldu mu" gibi isteklerde tetiklenir.
---

Filo geneli bir sorgu istendi. Bu becerinin amacı işi **güvenli** ve
**tekrarlanabilir** yapmaktır.

## Temel kural

Ad-hoc kabuk komutunu tüm filoda çalıştırma.

```
YANLIŞ:  ansible all -m shell -a "chronyc sources"
DOĞRU :  ansible-playbook -i envanter/hosts.yml playbooks/ntp_durum.yml
```

Sebep: ad-hoc `shell`/`command`/`raw` modülleri, senin ürettiğin rastgele
kabuk kodunun her sunucuda çalışması demektir. Bir yazım hatası ya da yanlış
anlaşılmış istek tüm filoyu etkiler. İzin sistemi bu modülleri zaten
reddediyor; reddedildiğini görürsen kuralı aşmaya çalışma, playbook yaz.

## Yordam

### 1. Envanter var mı, bak

```bash
ls envanter/ playbooks/ 2>/dev/null
ansible-inventory -i envanter/hosts.yml --list 2>/dev/null | head -40
```

Envanter yoksa kullanıcıya sor: hangi sunucular, hangi gruplar, hangi kullanıcı
ile bağlanılıyor. **Sunucu adı uydurma.**

### 2. İşe uygun playbook var mı, bak

`playbooks/` altında aradığın işi yapan bir dosya varsa onu kullan. Yoksa yeni
bir playbook yaz — kullanıcıya göstererek.

Yeni playbook yazarken:

- `gather_facts: false` — durum sorgusunda gereksiz, yavaşlatır
- `become: false` — durum okumak için root gerekmez; gerekiyorsa gerekçesini söyle
- `changed_when: false` — okuma görevleri "değişti" raporlamamalı
- `failed_when: false` — bir sunucudaki hata tüm çalıştırmayı düşürmesin
- `ignore_unreachable: true` — erişilemeyen sunucu raporda ayrıca görünsün
- Çıktıyı JSON olarak ver; metin ayrıştırmak yerine yapılandırılmış oku

Durum toplayan playbook ile düzelten playbook **ayrı dosyalar** olmalı.

### 3. Önce dar kapsamda dene

Tüm filoya gitmeden önce tek grupta çalıştır:

```bash
ansible-playbook -i envanter/hosts.yml playbooks/<ad>.yml --limit web
```

Çıktı beklediğin gibiyse `--limit`'i kaldır.

### 4. Değiştirmeden önce dur

Bir şeyi düzeltmen isteniyorsa:

- Önce `--check --diff` ile çalıştır ve ne değişeceğini göster
- Kullanıcının onayını al
- Onaysız uygulama

Zaman ayarını filo genelinde değiştirmek özellikle risklidir: saat atlaması
Kerberos biletlerini, TLS doğrulamasını ve veritabanı replikasyonunu bozabilir.

## chrony çıktısını yorumlama

`chronyc -n sources` çıktısı:

```
MS Name/IP address         Stratum Poll Reach LastRx Last sample
^* 10.0.0.1                      2   6   377    41   +12us[ +15us] +/-  12ms
^+ 10.0.0.2                      2   6   377    39   -31us[ -28us] +/-  15ms
^? 10.0.0.3                      0   6     0     -    +0ns[   +0ns] +/- 0ns
```

İlk sütun:

| İşaret | Anlamı |
|---|---|
| `^*` | **Şu an senkronize olunan kaynak.** Her sunucuda tam bir tane olmalı. |
| `^+` | Kabul edilebilir, yedek kaynak |
| `^-` | Birleştirme algoritması tarafından dışlandı |
| `^?` | Ulaşılamıyor |
| `^x` | Yanlış zaman veriyor (falseticker) |
| `^~` | Çok değişken, güvenilmez |

**Reach** sekizlik: `377` son 8 yoklamanın hepsi başarılı demektir. `377`
dışındaki her değer paket kaybına işaret eder. `0` hiç ulaşılamıyor.

`chronyc -n tracking` çıktısında bak:

- **Stratum** — 16 ise senkronize değil. Normal istemcide 3-4 beklenir.
- **System time** — sapma. Milisaniyeler normal, saniyeler sorun.
- **Leap status** — `Normal` olmalı; `Not synchronised` sorundur.

`timedatectl show --property=NTPSynchronized --value` → `yes` bekleniyor.

## Alarm eşikleri

Şunlardan biri varsa sorun bildir:

- `chronyd` çalışmıyor ya da etkin değil
- Hiç `^*` satırı yok — sunucu hiçbir kaynağa senkronize değil
- Stratum 16
- Sapma 1 saniyeden büyük
- Tüm kaynaklar `^?` — ağ ya da güvenlik duvarı sorunu (UDP 123)
- Sunucular farklı NTP kaynaklarına bakıyor — filo içi tutarsızlık

## Raporlama

Önce **özet**, sonra ayrıntı:

```
42 sunucu kontrol edildi.

SORUNLU (3)
  db02   chronyd durmuş
  web07  senkronize değil, stratum 16, tüm kaynaklar ulaşılamıyor
  app03  sapma 4.2s

ERİŞİLEMEDİ (1)
  old01  SSH bağlantısı kurulamadı

SAĞLAM (38)
```

Sağlam olanları tek tek listeleme, sayısını ver. Erişilemeyen sunucuları
"sağlam" sayma — ayrı başlıkta göster.

Düzeltme öner ama **kendiliğinden uygulama**.
