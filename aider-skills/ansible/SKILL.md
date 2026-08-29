---
name: ansible
description: Ansible ile birden çok sunucuda iş yaparken kullan — envanter doğrulama, ad-hoc komut, playbook çalıştırma, kuru çalıştırma. "ansible", "playbook", "envanter", "inventory", "hosts dosyası", "tüm sunucularda", "ansible-playbook" isteklerinde tetiklenir.
---

Doğrulandı: ansible-core 2.16.16, AlmaLinux 10.2 — 2026-08-29

Ansible tek makineyi değil **filoyu** etkiler; eksik `--limit` yüzlerce
sunucuya dokunur. Sıra: hangi yapılandırma etkin → envanter doğru mu → kuru
çalıştırma → gerçek çalıştırma.

## 1. Hangi ansible.cfg etkin

`ansible.cfg` çalışılan dizinden okunur. Hangisinin okunduğunu **varsayma**:

```bash
ansible --version | head -3          # "config file = ..." satırı
ansible-config dump --only-changed   # etkin ayarlar ve nereden geldiği
```

Ölçülen çıktı `CONFIG_FILE()` ve `DEFAULT_HOST_LIST()` satırlarını, yani
hangi dosyanın hangi envanteri getirdiğini gösterir.

**Tuzak: dizin herkese yazılabilirse (777) ansible.cfg sessizce yok sayılır.**
Ölçüldü — yalnızca bir uyarı basıyor ve `/etc/ansible/ansible.cfg`'ye düşüyor:

```
[WARNING]: Ansible is being run in a world writable directory
  config file = /etc/ansible/ansible.cfg
```

Belirti: "ayarım uygulanmıyor". `ls -ld .` ile bak, `chmod 755 .` ile düzelt.

Çalışma dizini tarihe göre ayrılmışsa (`.../ansible/temmuz/`, `.../agustos/`)
her klasörün kendi `ansible.cfg` ve `hosts` dosyası olur. Yanlış klasörden
çalıştırmak **sessizce yanlış envanteri** kullandırır. İlk iş doğru dizine
`cd` etmek, ikinci iş yukarıdaki `config file` satırını okumak.

## 2. Envanteri çalıştırmadan önce doğrula

INI envanter tamamen desteklidir; YAML'e geçmek zorunlu değil. Ama **ayrıştığını
gör**:

```bash
ansible-inventory --graph            # grup ağacı
ansible-inventory --host web01       # o hostun değişkenleri
ansible <grup> --list-hosts          # hangi makineler kapsanacak
```

`--graph` grup ağacını çizer (`@uretim` altında `@web`, `@db` gibi); beklediğin
makineler beklediğin grupta mı, orada görürsün.

**Bozuk INI hata vermez, sessizce boş envanter üretir.** Köşeli parantezi
kapatmayı unutmak yeterli; ölçülen sonuç:

```
[WARNING]: No inventory was parsed, only implicit localhost is available
```

Bu durumda playbook hiçbir sunucuya değmez ya da localhost'a çalışır. Her
zaman önce `--graph` ya da `--list-hosts`.

INI'de host değişkeni satır sonuna (`web01 ansible_host=10.0.0.11`), grup
değişkeni `[web:vars]` bloğuna, alt grup `[uretim:children]` bloğuna yazılır.

## 3. Çalıştırma sırası

```bash
ansible-playbook 01.ping.yaml --syntax-check      # yazım
ansible-playbook 01.ping.yaml --list-hosts        # kimi kapsıyor
ansible-playbook 01.ping.yaml --check             # kuru çalıştırma
ansible-playbook 01.ping.yaml --limit web         # daralt
ansible-playbook 01.ping.yaml                     # gerçek
```

Erişim testi için playbook şart değil:

```bash
ansible all -m ping
ansible <grup> -m command -a "chronyc sources"
```

`--check` her modülde desteklenmez; `command`/`shell` kuru çalıştırmada
atlanır — "değişiklik yok" çıktısı güvence değildir.

## 4. Çevrimdışı modül referansı

Modül seçeneklerini **ezberden yazma**. `ansible-doc` yerel belgedir, internet
gerektirmez:

```bash
ansible-doc -l | wc -l                       # kurulu modül sayısı
ansible-doc ansible.builtin.systemd_service  # seçenekler ve örnekler
ansible-doc -s ansible.builtin.copy          # kısa şablon
```

Ölçüldü: koleksiyonsuz bir ansible-core'da 71 modül var. Aradığın modül
listede yoksa koleksiyon eksiktir — çevrimdışı ortamda galaxy'den kurulum
çalışmaz, kullanıcıya sor.

## 5. Yan etkili — onaysız çalıştırma

```
ansible-playbook <p>.yaml       --limit yoksa TÜM envanter
-m command/shell                uzak makinede komut çalıştırır
-m file/copy/template           dosya değiştirir
-e "degisken=deger"             playbook değişkenini ezer
--become                        uzak makinede root'a yükselir
```

Çalıştırmadan önce **kimi kapsadığını göster** (`--list-hosts`) ve `--check`
çıktısını sun. Onay almadan gerçek çalıştırma yapma.

## Raporlama

`PLAY RECAP` satırlarını olduğu gibi yapıştırma; sorunluları ayır:

```
34 sunucu, 2 sorunlu
  db07   unreachable=1  -> ssh anahtarı ya da isim çözümleme
  web12  failed=1       -> "chronyc: command not found"
diğer 32: ok, changed=0
```

`unreachable` ile `failed` farklıdır: birincisi sunucuya ulaşılamadı
(ssh/isim), ikincisi ulaşıldı ama görev düştü. Teşhisin yönünü bu belirler.
