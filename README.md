# aider-agent

[Aider](https://github.com/Aider-AI/aider)'ın forku. Upstream aider kod
yazmak için tasarlandı; bu fork onu **sistem yönetimi ajanına** dönüştürüyor:
kurum içi, çevrimdışı bir OpenAI uyumlu endpoint'te (Qwen) çalışan, Claude
Code benzeri bir araç döngüsü.

Hedef ortam bir bankanın sunucu filosu: ağırlıkla **RHEL**, yanında birkaç
**Solaris 11 / LDOM**. Kod düzenleme yeteneği duruyor ama asıl iş sunucuya
bağlanmak, ölçmek, teşhis koymak ve raporlamak.

Fork noktası: upstream `5dc9490` (aider 0.86.3.dev).
Upstream'in kendi README'si: [`ORIJINAL-README.md`](ORIJINAL-README.md)

```
agent ⏸ plan modu>      araştırır, plan sunar, hiçbir dosyaya dokunmaz
agent ⏵ onay modu>      her yan etkili işlem için sorar
agent ⏵⏵ oto mod>       sormadan yürür
```

`shift+tab` modlar arasında dolaşır.

## Klasik aider'dan farkı

Aider tek atışlık çalışır: model bir düzenleme bloğu üretir, aider uygular.
Bu katman **agentic araç döngüsü** ekler — model `Read`, `Write`, `Edit`,
`Bash`, `Glob`, `Grep` ve `Ssh` araçlarını arka arkaya çağırır, çıktıyı görür,
işi bitirene kadar sürdürür.

| | Klasik aider | Agent modu |
|---|---|---|
| Akış | tek düzenleme | araç döngüsü |
| Komut çalıştırma | önerir | çalıştırır ve sonucu okur |
| İzin | `--yes` / soru | üç mod + kural tabanlı |
| Beceriler | yok | 37 beceri, kademeli açılım |
| MCP | yok | stdio istemcisi |
| Bellek | yok | proje talimatı + kalıcı not |

## Kurulum

**Ağa çıkabilen makine:**

```bash
git clone -b claude-code-layer https://github.com/alparslanozturk77/aider.git
cd aider
python3.12 -m venv venv && source venv/bin/activate
pip install .
```

> Dal açıkça yazılıyor. Varsayılan dal zaten `claude-code-layer`, ama depoda
> upstream aider'ı izleyen bir `main` dalı da var; oradan klonlarsan fork'un
> hiçbir dosyası gelmez.

> Sanal ortam şart. Sistem Python'una kurmayı denersen RHEL 9+ reddeder
> (`externally-managed-environment`); zorlarsan da yüz civarı bağımlılık
> `dnf`'in kullandığı site-packages'a karışır.

`pip install .` kopya kurar, yani `git pull` sonrası **yeniden kurmak
gerekir**. Sık güncelleyeceksen `pip install -e .` kullan: kod doğrudan
depodan okunur, pull yeter.

**Çevrimdışı sunucu (RHEL 9 / 10)** — bağımlılıklar paketin içinde wheel
olarak gelir, kurulum ağ istemez. [Sürüm sayfasından](https://github.com/alparslanozturk77/aider/releases)
indir:

```bash
tar -xzf aider-agent-<sürüm>-rhel10-x86_64.tar.gz
cd aider-agent-<sürüm> && ./cevrimdisi-kur.sh /opt/aider-agent
# ya da:  dnf install ./aider-agent-<sürüm>-1.el10.x86_64.rpm
```

> Sürüm numarası yayın sayfasındaki dosya adından gelir; burada sabit bir
> numara yazmak, olmayan bir dosyayı indirtmeye çalışır.

RHEL 9'da önce `dnf install python3.12` gerekir (sistem Python'ı 3.9, aider
`>=3.10` istiyor). RHEL 10'da sistem Python'ı zaten 3.12.

Derleme gerekmez. Sonra program içinden endpoint'i tanımla:

```
/model-ekle
```

Tek soru sorar: endpoint adresi. `/v1` yazmayı unutursan ekler; bağlam
penceresini `/v1/models` yanıtından okuyabilirse onu da sormaz.

Hava boşluklu sunucuda `~/.aider.conf.yml` dosyasına `offline: true` ekle —
sürüm denetimi, analitik ve URL çekme kapanır. Ağa çıkabilen makinede ekleme.

## Beceriler

Programla birlikte 37 beceri geliyor (`aider/beceriler/`), hangi dizinde
çalıştığından bağımsız olarak görünürler. Sistem promptuna yalnızca
`ad: açıklama` satırı girer; gövde model isteyince yüklenir, dolayısıyla
beceri sayısı bağlam maliyeti yaratmaz.

Sistem yönetimi (asıl kullanım): RHEL yönetimi ve sürüm farkları, ağ
teşhisi, SELinux, TLS sertifikaları, depolama ve disk ekleme (LVM/XFS),
performans ve log okuma, servis teşhisi (PostgreSQL/Redis/RabbitMQ), web
sunucusu, podman/docker, kurum registry'si (Nexus), Kubernetes/Rancher,
Satellite, sunucu teslimi, IdM, SSSD AD-trust, Splunk forwarder, güvenlik
ajanı keşfi, Solaris 11 / LDOM, rapor üretimi (CSV/HTML/xlsx/PDF).

Kod tarafı: kod inceleme, test yazma, güvenlik incelemesi, sadeleştirme,
hata ayıklama, beceri yazma ve geliştirme, MCP ekleme, upstream birleştirme,
belge yazma, git/AzureDevOps.

Becerilerdeki komutlar hafızadan yazılmadı; gerçek bir RHEL ailesi sunucuda
çalıştırılarak doğrulandı. Doğrulanamayan ortamlar için — Solaris, Satellite,
Rancher — komut referansı değil **keşif yordamı** yazıldı ve doğrulanmadığı
becerinin içinde açıkça belirtildi.

Yeni beceri: `/skills new <ad>`

## Belgeler

| Dosya | Ne için |
|---|---|
| [`AGENT.md`](AGENT.md) | Kullanım: kurulum, araçlar, izinler, MCP, komutlar |
| [`CLAUDE.md`](CLAUDE.md) | Depoda çalışacaklar için: mimari, kurallar, tuzaklar |
| [`BIRLESTIRME.md`](BIRLESTIRME.md) | Upstream'den güncelleme yordamı ve yamalar |

## Upstream'den güncelleme

```bash
./scripts/upstream_birlestir.sh
```

Sonrasında **zorunlu**:

```bash
venv/bin/python scripts/fork_dogrula.py
```

Bu betik fork'un yedi dokunuş noktasının hâlâ *çalıştığını* davranışsal olarak
sınar — dosyada metin aramaz, kodu gerçekten çağırır.

## Kapsam

Bilinçli olarak dar tutuldu: plan/oto mod, model ekleme, izin sistemi, MCP ve
beceriler. Subagent, hooks ve web araçları **kapsam dışı**.

## Lisans

Upstream aider ile aynı: Apache 2.0. Bkz. [`LICENSE.txt`](LICENSE.txt).
