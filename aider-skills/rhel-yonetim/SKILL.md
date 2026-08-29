---
name: rhel-yonetim
description: RHEL sunucularda sistem yönetimi yaparken kullan — servis, log, paket, abonelik, Satellite (hammer), IdM (ipa). "servis", "systemctl", "journalctl", "dnf", "satellite", "hammer", "ipa", "idm", "abonelik", "yama", "repo" isteklerinde tetiklenir.
---

## Bilmediğin komutu uydurma

Bu ortam çevrimdışı: bir aracın sözdizimini arayamazsın. `hammer`, `ipa` ve
`subscription-manager` alt komutları sürümden sürüme değişir ve ezberden
yazılan komut ya hata verir ya da **yanlış şeyi yapar**.

Kural: sözdizimini bilmiyorsan **önce yardım çıktısını oku**.

```bash
command -v hammer && hammer --version
hammer --help
hammer host --help
hammer host list --help
```

IdM için:

```bash
ipa help topics
ipa help commands | grep -i user
ipa user-find --help
```

Yardım çıktısını okumadan `hammer` ya da `ipa` komutu çalıştırma. Araç
kurulu değilse kullanıcıya söyle, tahmin yürütme.

## Uzak sunucuya bağlanırken

`ssh` varsayılan olarak ulaşılamayan bir adreste dakikalarca bekler. Uzak
komutlarda **her zaman** bağlantı zaman aşımı ver:

```bash
ssh -o ConnectTimeout=5 -o BatchMode=yes <sunucu> 'df -h'
```

`BatchMode=yes` parola sorulmasını engeller: anahtar yoksa komut takılmak
yerine hemen hata verir. Agent'ın terminali olmadığı için parola istemi
zaten cevaplanamaz.

### Sunucu adını UYDURMA

Kullanıcı `skyup` diyorsa komut `ssh skyup` olur. Başına `user@`, sonuna
`.kurum.local` gibi bir alan adı **EKLEME**. Bu adlar genelde
`~/.ssh/config` içinde tanımlı takma adlardır ve kullanıcı, anahtarı ve
gerçek adresi orada bir kez ayarlamıştır.

Adın çözülüp çözülmediğinden emin değilsen bağlanmayı denemeden önce bak:

```bash
ssh -G <ad> | head -3          # hostname, user, port
grep -iE "^Host " ~/.ssh/config
```

Takma ad tanımlı değilse kullanıcıya sor. Tahmin edilen bir adrese bağlanmayı
denemek en iyi ihtimalle zaman aşımı, en kötü ihtimalle yanlış sunucuya
bağlanmaktır.

Adres çözülmüyorsa önce onu söyle, bağlanmayı deneme:

```bash
getent hosts <sunucu> || echo "ad çözülemedi"
```

## Salt-okunur ile yan etkiliyi ayır

Önce durum topla, sonra değiştir. Değiştirmeden önce onay al.

**Güvenli, durum okuyan komutlar** — bunlar RHEL 8/9'da kararlıdır:

```bash
systemctl status <servis>
systemctl is-active <servis>
systemctl is-enabled <servis>
systemctl list-units --failed
journalctl -u <servis> -n 100 --no-pager
journalctl -p err -b --no-pager
dnf list installed <paket>
dnf check-update
rpm -qa | grep <paket>
subscription-manager status          # YALNIZCA RHEL
subscription-manager list --consumed # AlmaLinux/Rocky'de bu komut YOK
dnf repolist                         # her yerde çalışır, depo durumu
df -h ; free -m ; uptime
```

**Yan etkili komutlar** — onaysız çalıştırma:

```bash
systemctl start|stop|restart|enable|disable
dnf install|remove|update
subscription-manager register|attach|unregister
hammer ... create|update|delete|remove
ipa ... -add|-mod|-del
```

`ipa` komutlarında son ek fiili belirtir: `user-find` okur, `user-add` yazar,
`user-del` siler. `-find`, `-show`, `-status` okur; `-add`, `-mod`, `-del`
değiştirir.

## journalctl okurken

- `-n 100` olmadan çalıştırma; log devasa olabilir ve bağlamı doldurur
- `--no-pager` şart, yoksa komut takılır
- `-p err` yalnızca hata seviyesi ve üstünü verir — önce bununla bak
- `--since "1 hour ago"` ile daralt
- Servisin kendi log dosyası varsa (`/var/log/...`) onu da kontrol et

## Zarar verebilecek komutlar

Bunları **asla** onay almadan çalıştırma; izin sistemi çoğunu zaten reddediyor:

- `subscription-manager unregister` — sunucunun aboneliğini düşürür, yamalar durur
- `hammer host delete` — Satellite'ten sunucu kaydını siler
- `ipa host-del`, `ipa user-del` — kimlik kaydını siler, geri dönüşü zordur
- `dnf remove` — bağımlılıklarla birlikte beklenmedik paketleri kaldırabilir
- `systemctl stop` — üretim servisini durdurur
- `firewall-cmd --remove-*` — uzaktan erişimini kesebilirsin

Özellikle IdM'de: bir sunucuyu domainden çıkarmak (`ipa-client-install
--uninstall`) o sunucudaki tüm kimlik doğrulamayı bozar. Kendi bağlandığın
sunucuda çalıştırırsan oturumunu kaybedersin.

## Birden çok sunucu

Tek sunucudan fazlasına dokunacaksan `filo-durum-kontrolu` becerisine geç.
SSH döngüsü kurma, ad-hoc `ansible all -m shell` kullanma.

## Raporlama

Komutun **çıktısını** göster, özetleyip geçme — sistem yönetiminde ayrıntı
önemlidir. Ama uzun çıktıyı olduğu gibi yapıştırma; ilgili satırları seç ve
neden ilgili olduklarını söyle.

Bir şeyi doğrulamadıysan "çalışıyor" deme. Servisin ayakta olduğunu iddia
etmenin ölçüsü `systemctl is-active` çıktısını görmüş olmaktır.

## Bu becerinin sınırı

Burada `hammer` ve `ipa` için **komut referansı yok** — bilinçli olarak.
Sürüme bağlı oldukları için ezberden yazılmış bir referans yanlış bilgi
kaynağı olur.

Kendi ortamına özgü referansı oluşturmak için `beceri-yaz` becerisini kullan:
gerçek sunucuda `--help` çıktısından üretir, çalıştırarak doğrular ve sürüm
notu düşer.
