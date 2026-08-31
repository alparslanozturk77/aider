---
name: ansible
description: Ansible ile birden çok sunucuda iş yaparken kullan — proje düzeni kurma, envanter doğrulama, tek sunucuya daraltma, ad-hoc komut, playbook çalıştırma, kuru çalıştırma. "ansible", "playbook", "envanter", "inventory", "hosts dosyası", "tüm sunucularda", "şu sunucuda çalıştır", "ansible-playbook" isteklerinde tetiklenir.
---

Doğrulandı: ansible-core 2.16.16, AlmaLinux 10.2 — 2026-08-29
`--limit` davranışı ansible-core 2.15.13'te ölçüldü — 2026-08-31

Ansible tek makineyi değil **filoyu** etkiler; eksik `--limit` yüzlerce
sunucuya dokunur. Sıra: proje düzeni → hangi cfg etkin → envanter doğru mu →
kimi kapsıyor → kuru çalıştırma → gerçek çalıştırma.

## 1. Proje düzeni — ilk iş

Ansible işleri kendi klasöründe durur; **her proje kendi yapılandırmasını ve
kendi envanterini taşır**. Playbook yazmadan ÖNCE bu ikisini oluştur:

```
ansible/
  ansible.cfg          [defaults] altında: inventory = hosts-<proje>.ini
  hosts-<proje>.ini    envanter, INI biçimi
  site.yml             playbook
```

Envanter adında proje geçer (`hosts-uretim.ini`), yalın `hosts` değil — bir
dizinde birden çok envanter durabilir, hangisinin ne olduğu ancak adından
anlaşılır. INI biçimi yeterlidir, YAML'e geçme:

```ini
[web]
web01 ansible_host=10.0.0.11
[uretim:children]
web
```

Host değişkeni satır sonuna, grup değişkeni `[web:vars]`, alt grup
`[uretim:children]` bloğuna yazılır.

Düzenin karşılığı: doğru dizine `cd` ettiğin an doğru envanter etkin olur.
`-i` verirsen cfg'deki envanteri **ezer**; ikisi farklıysa çalışan `-i`'dir.

## 2. Hangi ansible.cfg etkin

`ansible.cfg` çalışılan dizinden okunur. Hangisi okundu, **varsayma**:

```bash
ansible --version | head -3          # "config file = ..." satırı
ansible-config dump --only-changed   # etkin ayarlar ve kaynağı
```

**Tuzak: dizin herkese yazılabilirse (777) ansible.cfg sessizce yok sayılır.**
Ölçüldü — uyarı basıp `/etc/ansible/ansible.cfg`'ye düşüyor:

```
[WARNING]: Ansible is being run in a world writable directory
```

Belirti: "ayarım uygulanmıyor". `ls -ld .` ile bak, `chmod 755 .` ile düzelt.

## 3. Envanteri çalıştırmadan önce doğrula

```bash
ansible-inventory --graph            # grup ağacı
ansible-inventory --host web01       # o hostun değişkenleri
ansible <grup> --list-hosts          # kimi kapsıyor
```

**Bozuk INI hata vermez, sessizce boş envanter üretir.** Kapatılmayan köşeli
parantez yeterli; ölçülen sonuç:

```
[WARNING]: No inventory was parsed, only implicit localhost is available
```

O hâlde playbook hiçbir sunucuya değmez ya da localhost'a çalışır.

## 4. Tek sunucuda çalıştırma

Envanterin tamamı yerine tek makine için `-l` (`--limit`):

```bash
ansible-playbook -i hosts-uretim.ini site.yml -l web01     # tek sunucu
ansible-playbook -i hosts-uretim.ini site.yml -l web       # tek grup
ansible-playbook -i hosts-uretim.ini site.yml -l 'web01,db01'
ansible -i hosts-uretim.ini web01 -m ping                  # ad-hoc
```

Kullanıcı "şu sunucuda" dediğinde varsayılan yol budur; playbook'un `hosts:`
satırını değiştirme, `-l` ile daralt.

Yazım hatası **sessizce geçmez** — ölçüldü, çıkış kodu 1 ile düşer:

```
[WARNING]: Could not match supplied host pattern, ignoring: yok-boyle-bir-sey
ERROR! Specified inventory, host pattern and/or --limit leaves us with no hosts to target.
```

Tersi güvence değil: **doğru yazılmış ama yanlış makineyi gösteren ad** hata
vermez, sessizce oraya çalışır. Gerçek çalıştırmadan önce her zaman
`--list-hosts`.

## 5. Çalıştırma sırası

```bash
ansible-playbook site.yml --syntax-check         # yazım
ansible-playbook site.yml -l web01 --list-hosts  # kimi kapsıyor
ansible-playbook site.yml -l web01 --check       # kuru çalıştırma
ansible-playbook site.yml -l web01               # gerçek
```

`--check` her modülde desteklenmez; `command`/`shell` kuru çalıştırmada
atlanır — "değişiklik yok" çıktısı güvence değildir.

## 6. Modül seçeneklerini ezberden yazma

`ansible-doc` yerel belgedir, ağ istemez:

```bash
ansible-doc ansible.builtin.systemd_service  # seçenekler ve örnekler
ansible-doc -s ansible.builtin.copy          # kısa şablon
ansible-doc -l | wc -l                       # kurulu modül sayısı
```

Ölçüldü: koleksiyonsuz ansible-core'da 71 modül var. Modül listede yoksa
koleksiyon eksiktir — çevrimdışı ortamda galaxy kurulumu çalışmaz, sor.

## 7. Yan etkili — onaysız çalıştırma

```
ansible-playbook <p>.yml     -l/--limit yoksa TÜM envanter
-m command/shell             uzak makinede komut çalıştırır
-m file/copy/template        dosya değiştirir
-e "degisken=deger"          playbook değişkenini ezer
--become                     uzak makinede root'a yükselir
```

Önce **kimi kapsadığını göster** (`--list-hosts`) ve `--check` çıktısını sun.

## Raporlama

`PLAY RECAP` satırlarını olduğu gibi yapıştırma; sorunluları ayır:

```
34 sunucu, 2 sorunlu
  db07   unreachable=1  -> ssh anahtarı ya da isim çözümleme
  web12  failed=1       -> "chronyc: command not found"
diğer 32: ok, changed=0
```

`unreachable` ulaşılamadı (ssh/isim), `failed` ulaşıldı ama görev düştü.
Teşhisin yönünü bu ayrım belirler.
