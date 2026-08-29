---
name: rhel-surumleri
description: RHEL 7, 8, 9 ve 10 arasındaki komut ve yapılandırma farklarında kullan. Bir komut bir sunucuda çalışıp diğerinde çalışmadığında. "rhel 7", "rhel 8", "rhel 9", "rhel 10", "centos", "almalinux", "rocky", "sürüm farkı", "eski sunucu" isteklerinde tetiklenir.
---

## Önce sürümü öğren

```bash
cat /etc/os-release | grep -E '^(NAME|VERSION_ID)='
rpm -E %{rhel}                 # yalnızca ana sürüm: 7, 8, 9, 10
```

Karışık filoda **komut yazmadan önce bunu çalıştır.** Aynı komut RHEL 7'de
çalışıp 10'da çalışmıyor olabilir.

AlmaLinux, Rocky ve CentOS Stream, RHEL ile aynı ana sürüm numarasını izler ve
aşağıdaki farklar onlarda da geçerlidir. Tek istisna abonelik yönetimi:
`subscription-manager` yalnızca RHEL'de vardır.

## Sürüm farkları

| Konu | RHEL 7 | RHEL 8 | RHEL 9 | RHEL 10 |
|---|---|---|---|---|
| Paket | `yum` | `dnf` (`yum` takma ad) | `dnf` | `dnf` |
| Python | 2.7 + 3.6 | 3.6 modül | 3.9, **py2 yok** | 3.12 |
| Ağ yapılandırma | `network-scripts` | ikisi de | NM keyfile, scripts kullanımdan kalkıyor | **yalnızca NM keyfile** |
| `ifconfig`/`netstat` | var | `net-tools` ile | ayrı kurulur | **yok, `ip`/`ss` kullan** |
| Güvenlik duvarı | firewalld/iptables | firewalld/nftables | nftables | nftables |
| Konteyner | docker | **podman** | podman | podman |
| Init/servis | systemd | systemd | systemd | systemd |
| Kripto politikası | yok | `update-crypto-policies` | aynı | aynı, daha sıkı |

RHEL 10 satırları AlmaLinux 10.2'de çalıştırılarak doğrulandı. 7/8/9 satırları
belgeye dayanıyor — o sürümde bir sunucun varsa oradan teyit et.

## En sık çarpılan üç fark

### 1. `ifconfig` ve `netstat` yok

```bash
ifconfig                 # RHEL 9+ : command not found
netstat -tlnp            # aynı

ip addr                  # yerine
ip route
ss -tlnp
```

Eski script'lerin RHEL 9/10'a taşınırken buradan kırılır.

### 2. Ağ yapılandırma dosyaları taşındı

```bash
# RHEL 7/8
/etc/sysconfig/network-scripts/ifcfg-eth0

# RHEL 9/10 (keyfile biçimi)
/etc/NetworkManager/system-connections/*.nmconnection
```

RHEL 10'da `network-scripts` dizini **yoktur**. Elle dosya düzenlemek yerine
`nmcli` kullan; her sürümde çalışır:

```bash
nmcli connection show
nmcli connection modify <ad> ipv4.addresses 10.0.0.5/24
nmcli connection up <ad>
```

### 3. Kripto politikası bağlantı kesiyor

RHEL 8'den itibaren sistem geneli kripto politikası var. RHEL 9 ve 10'da
sıkılaştı: SHA-1 imzalar ve eski TLS sürümleri varsayılan olarak reddedilir.

Belirti: eski bir sunucuya ya da cihaza SSH/TLS bağlantısı "no matching
key exchange method" ile düşer.

```bash
update-crypto-policies --show          # DEFAULT, LEGACY, FUTURE, FIPS
```

Geçici olarak gevşetmek (yan etkili, **onay al**, sistem genelini etkiler):

```bash
update-crypto-policies --set LEGACY
```

Tercih edilen yol: yalnızca o bağlantı için istisna tanımla, sistem genelini
düşürme.

## Python bağımlılığı

RHEL 9'dan itibaren Python 2 **yok**. `#!/usr/bin/python` ile başlayan eski
script'ler çalışmaz; `python3` yaz. Ansible için hedefte
`ansible_python_interpreter: /usr/bin/python3` ayarla.

## Raporlama

Bir komut bir sunucuda çalışıp diğerinde çalışmıyorsa, önce iki sunucunun
sürümünü yan yana göster. Farkın nereden geldiğini söylemeden çözüm önerme.
