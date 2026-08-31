---
name: guvenlik-ajani
description: Symantec SEP ya da Palo Alto Cortex XDR ajanı incelerken kullan — kurulu mu, çalışıyor mu, sürümü ne, tanım güncel mi. "sep", "symantec", "cortex", "xdr", "cytool", "antivirüs", "ajan", "endpoint" isteklerinde tetiklenir.
---

## Bu beceri komut referansı DEĞİL, keşif yordamıdır

SEP ve Cortex XDR'ın komut satırı sürümden sürüme belirgin şekilde değişiyor.
Ezberden yazılmış bir referans burada yanlış olur — güvenlik ajanında yanlış
komut, en iyi ihtimalle hata verir, en kötüsünde korumayı kapatır.

Bu yüzden aşağıdaki adımlar sana **kendi ortamındaki gerçek komutları
buldurur.** Bulduklarını kalıcı bir referansa çevirmek için `beceri-yaz`
becerisine geç.

## 1. Ajan kurulu mu, hangisi

```bash
rpm -qa | grep -iE 'sep|symantec|sav|cortex|traps|paloalto|cyvera'
ls -d /opt/Symantec /opt/traps /opt/paloaltonetworks /opt/cortex 2>/dev/null
systemctl list-units --type=service --all | grep -iE 'sep|symantec|traps|cortex|cyserver'
```

Hiçbiri sonuç vermiyorsa ajan kurulu değildir — kuruluymuş gibi devam etme,
kullanıcıya söyle.

## 2. Çalıştırılabilir dosyayı bul

```bash
rpm -ql <paket-adı> | grep -E '/(bin|sbin)/'
find /opt -maxdepth 3 -type f -perm -u+x 2>/dev/null | grep -iE 'sep|sav|cytool|traps'
```

Yaygın adlar — ama **doğrulamadan kullanma**:

| Ürün | Muhtemel CLI | Muhtemel yol |
|---|---|---|
| Symantec SEP for Linux | `sav`, `symcfg`, `sepfl` | `/opt/Symantec/symantec_antivirus/` |
| Cortex XDR | `cytool` | `/opt/traps/bin/`, `/opt/paloaltonetworks/` |

## 3. Sözdizimini araçtan öğren

```bash
<bulunan-komut> --help
<bulunan-komut> help
```

`cytool` için alt komutlar genelde `cytool <alan> <eylem>` biçimindedir;
alanları `cytool --help` listeler.

**Çıktıyı oku, ezberden alt komut yazma.**

## 4. Salt-okunur durum kontrolleri

Yalnızca *okuyan* komutlarla başla. Tipik olarak aranan bilgiler:

- Ajan çalışıyor mu (`systemctl is-active <servis>`)
- Ajan sürümü
- Tanım/imza sürümü ve tarihi — **güncel mi**
- Yönetim sunucusuna bağlantı durumu
- Son tarama zamanı ve sonucu
- Karantinadaki nesneler

Her biri için komutu 3. adımdaki yardım çıktısından çıkar.

Servis ve log tarafı ajandan bağımsız, her zaman çalışır:

```bash
systemctl status <servis> --no-pager
journalctl -u <servis> -n 100 --no-pager
ls -lt /var/log/ | grep -iE 'sep|symantec|traps|cortex' | head
```

## 5. ASLA onaysız çalıştırma

Güvenlik ajanını durdurmak ya da korumayı kapatmak, sunucuyu savunmasız
bırakır ve çoğu kurumda uyumluluk ihlalidir:

- Ajan servisini `stop` / `disable` etme
- Koruma modunu değiştirme, "self-protection" kapatma
- Karantinadan dosya geri yükleme
- Ajanı kaldırma
- Tanım güncellemesini devre dışı bırakma

Bunlardan biri gerekiyorsa kullanıcıya *neden* gerektiğini sor, onayını al ve
sonra geri açmayı hatırlat.

## 6. Kurulum

Kurulum paketi ve lisans kuruma özgüdür; genel bir yordam uydurma.
Kullanıcıdan kurulum paketinin yolunu ve varsa dağıtım yöntemini (Satellite,
Ansible, yönetim konsolu push) iste.

Kurulum sonrası doğrulama her zaman aynı: servis çalışıyor mu, sürüm ne,
yönetim sunucusuna kayıt oldu mu, tanımlar güncellendi mi.

## Raporlama

Hangi ajanın, hangi sürümünün kurulu olduğunu ve tanımların **ne kadar eski**
olduğunu söyle. "Ajan çalışıyor" yetmez: tanımı üç ay eski bir ajan çalışıyor
görünür ama korumaz.

Komutu yardım çıktısından çıkardıysan bunu belirt; ezberden yazdıysan zaten
yazmamalıydın.
