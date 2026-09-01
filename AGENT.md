# Agent Modu — aider için Claude Code benzeri katman

Bu fork, aider'a gerçek bir **tool-calling döngüsü**, **SKILL.md tabanlı beceri
sistemi** ve **plan modu** ekler. Upstream aider'ın tüm mevcut davranışı olduğu
gibi korunur; agent modu ek bir `edit-format` olarak gelir.

## Klasik aider ile farkı

Klasik aider tek atımlıdır: bağlamın tamamını gönderir, yanıttaki *edit
block*'ları uygular, durur. Modelin kendi başına dosya okuması, komut
çalıştırması ya da ara sonuca göre yön değiştirmesi mümkün değildir.

Agent modu bunun yerine bir döngü kurar:

```
kullanıcı mesajı
      ↓
  model karar verir ──→ araç çağırır ──→ sonucu görür ─┐
      ↑                                                │
      └────────────────────────────────────────────────┘
                  (iş bitene kadar)
```

Model dosyayı kendisi bulur, kendisi okur, testi kendisi çalıştırır ve çıktıya
göre bir sonraki adıma karar verir.

## Kurulum

Tek satır:

```bash
curl -fsSL https://raw.githubusercontent.com/alparslanozturk77/aider/claude-code-layer/kur.sh | sh
```

Betik `uv`'yi (yoksa) kurar, aider-agent'ı izole bir ortama yerleştirir ve
`aider` komutunu PATH'e koyar. **Sanal ortam kurman ya da yönetmen gerekmez;
uv hepsini gizler.** Aynı komut güncelleme için de çalışır.

Sonra modelini programın içinden tanıt:

```bash
aider --agent
/model-ekle
```

`/model-ekle` endpoint tipini, model kimliğini, adresi, anahtarı ve bağlam
penceresini sorar; ev dizinindeki üç yapılandırma dosyasını yazar
(`~/.aider.conf.yml` 0600 izniyle, çünkü anahtar taşıyor). Tanım tüm
projelerde geçerli olur.

Model kimliğini bilmiyorsan:

```bash
curl -s "$OPENAI_API_BASE/models" \
  -H "Authorization: Bearer $OPENAI_API_KEY" | jq -r '.data[].id'
```

### Oturumlar ve kaldığı yerden devam

```bash
aider --agent --continue      # son oturumu sürdür
/oturumlar                    # kayıtlı oturumları listele
```

Her oturum `.aider/sessions/<damga>.jsonl` dosyasına, mesajlar **API'ye
gönderildiği biçimde** yazılır. Yani araç çağrıları ve sonuçları da geri
gelir; sohbet kaldığı yerden sürer.

Upstream'in `--restore-chat-history`'si bu iş için kullanılamıyor: markdown
sohbet günlüğünün tamamını okuyup ayrıştırıyor (dosya aylar içinde yüz
kilobaytları buluyor) ve `tool_calls` ile `role="tool"` mesajlarını
kaybediyor. Agent modunda geçmişin yarısı araç trafiği olduğu için bu,
geçmişin yarısını atmak demek.

Ayrıntılar:

- Satır satır yazılır; program çökerse o ana kadarki geçmiş elde kalır ve
  yarım kalan son satır gerisini bozmaz.
- Geri yükleme bağlam penceresinin **%30'una** kırpılır (tavan 40k karakter).
  Kırpma noktası ileri alınıp ilk `user` mesajına hizalanır — `tool_calls`
  taşıyan bir assistant mesajı ile ona ait `tool` yanıtları ayrılırsa
  endpoint isteği reddediyor.
- Elli oturumdan eskisi budanır.
- Kayıt hatası oturumu düşürmez; bir kez uyarılır ve kayıt kapanır.

Dosyalar `.aider/` altında olduğu için `.gitignore`'daki `.aider*` kuralıyla
depoya girmezler. Komut çıktıları içerdiklerinden bu bilinçli.

### Çevrimdışı mod

Hava boşluklu bir kurum sunucusunda:

```bash
aider --agent --offline
```

Ağa çıkan her davranışı tek noktadan kapatır:

| Kapatılan | Neden |
|---|---|
| Sürüm denetimi | `--check-update` varsayılan AÇIK ve altındaki `requests.get` **zaman aşımsız**; ağ yoksa açılış TCP zaman aşımı kadar bekliyor |
| Analitik (PostHog) | Açılışta etkinleşip kullanım olaylarını dışarı gönderiyor |
| URL çekme | Sohbetteki adresleri indirmeyi öneriyor |
| `/voice` | `aider/voice.py` `api_base`'i iletmiyor; ses kaydı `api.openai.com`'a giderdi |
| `npx`/`uvx` ile başlayan MCP sunucuları | Paketi ağdan indirirler; çevrimdışında sessizce takılıyorlar |

Kalıcı yapmak için `~/.aider.conf.yml` dosyasına:

```yaml
offline: true
```

MCP sunucusu kullanacaksan paketi önceden kur ve `command` alanına doğrudan
çalıştırılabilir yolu yaz (`npx` değil).

### Repo haritası

Agent modunda **varsayılan olarak kapalı**. Aider'ın klasik akışında harita
modele yön vermek için gerekliydi; burada modelin Glob, Grep ve Read araçları
var, aradığını kendisi buluyor. Harita ise her isteğe yeniden gömülüyor ve
sohbete dosya eklenmemişken sekiz katına çıkıyor.

İstersen aç:

```bash
aider --agent --map-tokens 1024
```

### Depodan kurulum (klon + venv, proxy arkasında)

`kur.sh` ağa çıkıp `uv` indirir. Kurum ağında bu engelliyse ya da elinde zaten
bir klon varsa doğrudan depodan kur:

```bash
# RHEL 9: sistem Python'ı 3.9, aider >=3.10 istiyor
dnf install -y python3.11 git
git clone https://github.com/alparslanozturk77/aider.git /opt/aider
cd /opt/aider
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
ln -sf /opt/aider/.venv/bin/aider /usr/local/bin/aider
```

Proxy arkasındaysan pip'e adresi ver:

```bash
export https_proxy=http://proxy.kurum.local:8080
export http_proxy="$https_proxy"
# ya da tek seferlik:
.venv/bin/python -m pip install --proxy "$https_proxy" -e .
```

`-e` (editable) bilinçli: kod venv'e kopyalanmaz, klondan çalışır. Güncelleme
`git pull`'dan ibaret kalır.

Son satırdaki sembolik bağ sayesinde her yerden sadece `aider` yazarsın.
`ln` yerine `ln -s` kullan; sert bağ farklı dosya sistemlerinde çalışmaz.

**Çalışma dizini kurulum dizini olmak zorunda değil.** Klonu `/opt/aider`'a
koyup `/root/is` içinde çalışabilirsin; beceriler programın içinde taşındığı
için her dizinde görünürler.

### Güncelleme

| Kurulum | Güncelleme |
|---|---|
| `kur.sh` (uv) | `./kur.sh` yeniden çalıştır (`uv tool install --force`) |
| klon + `pip install -e .` | `git pull` yeter |
| klon + `pip install .` | `git pull`, sonra `pip install --no-deps .` |
| çevrimdışı paket / RPM | yeni paketi indirip kur |

Hangisinde olduğunu şununla gör:

```bash
.venv/bin/python -m pip show aider-chat | grep -i editable
```

"Editable project location" satırı varsa `git pull` yeter.

`git pull` yalnızca **bağımlılık listesi değişmediyse** kendi başına yeter;
`requirements.txt` değiştiyse kurulum ağa çıkmak zorunda:

```bash
git pull
.venv/bin/python -m pip install -e .    # yalnızca requirements değiştiyse
```

Agent katmanı (beceriler, slash komutları, sistem promptu) saf Python ve
Markdown; yeni bağımlılık eklenmedikçe hepsi `git pull` ile gelir.

### Neden venv değil de uv?

Bağımlılık ağacı büyük — kurulum ~630 MB, tek başına
`tree-sitter-language-pack` 351 MB (aider'ın repo haritası için, upstream
bağımlılığı). Bu boyutta gerçek bir tek-dosya ikili (PyInstaller/shiv)
mantıklı değil: çok büyük olur ve her platform için ayrı derlenmesi gerekir.

`uv` bu sorunu farklı çözüyor: kendisi 36 MB'lık tek statik ikili, Python'u da
kendi indiriyor, ve `uv tool install` uygulamayı senin görmediğin izole bir
ortama kuruyor. Sonuç kullanıcı açısından Claude Code'a en yakın deneyim:
bir kurulum komutu, sonra sadece `aider`.

### RHEL 8 / RHEL 9 (ve diğer Linux)

**Derleme gerekmez.** Bağımlılıkların tamamının hazır `manylinux` wheel'i var —
x86_64 ve aarch64, Python 3.11 ve 3.12 için. `gcc`, `python3-devel` ya da
`rust` kurmana gerek yok.

**Python sürümü tek gerçek engel:**

| Dağıtım | Varsayılan `python3` | Yeterli mi |
|---|---|---|
| RHEL 8 | 3.6 | hayır |
| RHEL 9 | 3.9 | hayır |

Aider `>=3.10` istiyor. İki çözüm var:

*Yol 1 — `kur.sh` (önerilen).* `uv` uygun Python'u kendisi indirir, sistem
Python'una hiç dokunmaz. RHEL 8'de bile ek paket gerekmez:

```bash
sudo dnf install -y git
curl -fsSL https://raw.githubusercontent.com/alparslanozturk77/aider/claude-code-layer/kur.sh | sh
```

*Yol 2 — AppStream Python ile elle.* Sistemde bir Python istiyorsan:

```bash
sudo dnf install -y git python3.12 python3.12-pip
git clone https://github.com/alparslanozturk77/aider.git && cd aider
python3.12 -m venv .venv && .venv/bin/pip install -e .
```

RHEL 8'de `python3.12` yoksa `python3.11` de çalışır.

**İsteğe bağlı sistem paketleri:**

- `ripgrep` — Grep aracı varsa onu kullanır, yoksa saf Python yedeğine düşer.
  Sonuç aynı, büyük depolarda yalnızca daha yavaş. RHEL temel depolarında yok;
  EPEL'den gelir. Kurmasan da olur.
- `libsndfile` / `portaudio` — yalnızca aider'ın sesli giriş özelliği için.
  Yoksa import korumalı biçimde atlanır ve aider normal açılır. Agent modu
  bunları hiç kullanmaz.

**Çevrimdışı / kapalı ağ.** Kurum sunucusu PyPI'a çıkamıyorsa wheel'leri
internete çıkabilen bir makinede indirip taşı:

```bash
pip download -d wheels -r requirements.txt \
    --platform manylinux_2_28_x86_64 --python-version 3.12 --only-binary=:all:
# hedef makinede:
pip install --no-index --find-links wheels -e .
```

### Elle kurulum (geliştirme için)

```bash
git clone https://github.com/alparslanozturk77/aider.git && cd aider
python3.12 -m venv .venv && .venv/bin/pip install -e .
cp ornek/env .env
cp ornek/aider.conf.yml .aider.conf.yml
mkdir -p .aider && cp ornek/permissions.yml .aider/permissions.yml
.venv/bin/aider --agent
```

> **Önemli:** Agent modu modelin **function calling** desteklemesini gerektirir.
> Qwen2.5-Coder ve Qwen3-Coder ailesi bunu destekler, ancak sunucu tarafında da
> açık olmalıdır. vLLM için sunucu şu bayrakla başlatılmalıdır:
> `--enable-auto-tool-choice --tool-call-parser hermes`
> Bu açık değilse model araç çağıramaz ve düz metin yanıt verir.

## Çevrimdışı kurulum paketleri (RHEL 9 / 10)

`kur.sh` internete çıkar (uv indirir, depoyu klonlar). Ağa çıkamayan bir
sunucuda işe yaramaz. Onun için iki paket biçimi var; ikisi de bağımlılıkları
**wheel olarak içinde taşır** ve kurulum anında ağ istemez.

| Biçim | Ne zaman |
|---|---|
| `.tar.gz` | Tek sunucuya elle kurulum. Kök yetkisi şart değil. |
| `.rpm` | Filoya dağıtım. Satellite'ta özel depoya konabilir. |

Sürüm sayfasından indirilir:
<https://github.com/alparslanozturk77/aider/releases>

### tgz

```bash
tar -xzf aider-agent-0.1.0-rhel10-x86_64.tar.gz
cd aider-agent-0.1.0
./cevrimdisi-kur.sh /opt/aider-agent      # hedef dizin isteğe bağlı
aider-agent --version
```

Betik uygun Python'u kendisi arar (3.10–3.14), sanal ortamı `--no-index` ile
kurar ve `/usr/local/bin/aider-agent` sarmalayıcısını yazar (yazma yetkisi
yoksa atlar ve tam yolu söyler).

### RPM

```bash
dnf install ./aider-agent-0.1.0-1.el10.x86_64.rpm
aider-agent --version
```

`/opt/aider-agent` altına kurulur, sanal ortam `%post` içinde ağa çıkmadan
oluşturulur. Kaldırınca (`dnf remove`) sanal ortam da silinir.

### RHEL 9'da Python sürümü

**Bu, RHEL 9'da ilk karşılaşacağın engel.** Aider `>=3.10` istiyor
(`pyproject.toml`), RHEL 9'un sistem Python'ı ise 3.9. AppStream'den kurulur:

```bash
dnf install python3.12
```

RHEL 10'da sistem Python'ı zaten 3.12 (doğrulandı: AlmaLinux 10.2), ek bir
şey gerekmez.

### Paketleri kendin üretmek

`.github/workflows/paket-rhel.yml` iş akışı `almalinux:9` ve `almalinux:10`
konteynerlerinde ikisini de üretir; `agent-v*` etiketi push edilince çalışır
ve dosyaları sürüme ekler. Elle de tetiklenebilir (workflow_dispatch).

Yerelde üretmek için `paketleme/` altındaki `aider-agent.spec` ve
`cevrimdisi-kur.sh` yeterlidir.

**Pakete belge sitesi ve testler girmez** (`aider/website` tek başına 68 MB);
çalışma zamanında gerekmiyorlar. Wheel'lerle birlikte paket ~115 MB.

### Yalnızca en son sürümün paketi tutulur

Sürüm başına ~230 MB (iki RHEL sürümü). Her sürümde biriktirmenin faydası
yok — kurulacak olan her zaman en güncelidir. İş akışının son adımı, yeni
paketler yüklendikten sonra **eski sürümlerin `.tar.gz` ve `.rpm`
dosyalarını siler.**

Silinen yalnızca ikili dosyalardır: eski sürümlerin kendisi, notları ve
etiketleri durur, dolayısıyla `git checkout agent-v0.1.0` ile eski koda her
zaman dönebilirsin — sadece hazır paketi yeniden üretmen gerekir
(workflow_dispatch ile o etiketten tetiklenebilir).

Actions artefaktları da 7 gün sonra düşer (`retention-days: 7`).

## Araçlar

| Araç | Ne yapar | Onay ister |
|---|---|---|
| `Read` | Dosyayı satır numaralı okur; `offset`/`limit` ile parça parça | hayır |
| `Write` | Dosyayı tamamen yazar, üstüne yazar | **evet** |
| `Edit` | Birebir string değişimi; belirsiz eşleşmede hata verir | **evet** |
| `Bash` | Kabuk komutu çalıştırır, zaman aşımlı | **evet** |
| `Ssh` | Uzak sunucuda komut çalıştırır; adı doğrular | **evet** |
| `Glob` | Desene uyan dosyaları bulur, tarihe göre sıralı | hayır |
| `Grep` | İçerikte regex arar; ripgrep varsa onu kullanır | hayır |
| `TodoWrite` | Çok adımlı işlerde görev listesi tutar | hayır |
| `Skill` | Bir beceriyi bağlama yükler | hayır |
| `Hatirla` | Kalıcı not kaydeder | **evet** |
| `ExitPlanMode` | Planı onaya sunar (yalnızca plan modunda) | **evet** |

### Ssh ve sunucu adları

Model `ssh` komutunu Bash ile kendisi kurunca sunucu adını uyduruyor —
gözlendi: kullanıcı "skyup" dedi, model `ssh skyup@kurum.local` üretti.
Ayrı bir araç olmasının sebebi bu.

Sunucu adı üç kaynakta aranır:

1. `~/.ssh/config` — takma adlar
2. `~/.ssh/known_hosts` — daha önce bağlanılmış makineler (karma girdiler
   geri çözülemediği için atlanır)
3. **ansible envanterleri** — proje kökünde ve bir alt dizinde `hosts*.ini`,
   `hosts*.yml`, `inventory*`

Üçünde de yoksa komut **reddedilmez, kullanıcıya sorulur**: public-key
kimlik doğrulaması kurulmuş ve DNS'te çözülen bir sunucu (`ssh srvsatellite
"komut"`) hiçbir yapılandırma dosyasında görünmeyebilir. Bu soru oto modda
bile sorulur ve onaylanan ad oturum boyunca hatırlanır.

`user@` eklenmiş bir ad her zaman reddedilir. Alan adı içeren ad ise yalnızca
bilinen kaynaklarda yoksa reddedilir — `known_hosts` pekâlâ FQDN tutuyor
olabilir.

Onay davranışı izin sistemiyle yönetilir; aşağıya bak.

`Grep` ve `Glob`, `.git`, `node_modules`, `__pycache__`, `venv`, `dist` gibi
dizinleri hiçbir zaman taramaz. Araç çıktıları bağlam penceresini yutmasın diye
30.000 karakterde kırpılır.

## Beceriler (Skills)

Beceri, bir klasör ve içinde YAML frontmatter'lı bir `SKILL.md` dosyasıdır:

```
.aider/skills/
  kod-inceleme/
    SKILL.md
  test-yaz/
    SKILL.md
```

```markdown
---
name: kod-inceleme
description: Bir değişikliği gözden geçirirken kullan. "incele", "review",
  "gözden geçir" isteklerinde tetiklenir.
---

Bir değişikliği incelerken şu sırayı izle.

## 1. Kapsamı belirle
...
```

Mekanizma **kademeli açılım** üzerine kuruludur: sistem promptuna yalnızca
`ad: açıklama` satırı girer (ucuz). Model işin bir beceriyle örtüştüğünü fark
edince `Skill` aracını çağırır ve gövdenin tamamı ancak o zaman bağlama yüklenir.
Bu sayede onlarca beceri tanımlamak bağlam maliyeti yaratmaz.

`description` alanı zorunludur ve becerinin **ne zaman kullanılacağını**
anlatmalıdır — model tetikleme kararını yalnızca buna bakarak verir. Açıklaması
olmayan beceriler sessizce atlanır.

Aranan dizinler, öncelik sırasıyla:

1. `<proje>/.aider/skills/` — kişisel, depoya **girmez** (`.aider*` ignore'da)
2. `<proje>/aider-skills/` — takımla paylaşılan, depoya girer
3. `~/.aider/skills/` — tüm projelerde geçerli kişisel beceriler
4. `AIDER_SKILLS_PATH` içindeki dizinler — kurum geneli ortak beceriler
5. `aider/beceriler/` — programla birlikte gelen 37 beceri

Aynı isim birden fazla yerde varsa **ilk kök kazanır**. Sıra bilinçli: paylaşılan
bir beceriyi lokalde geçici olarak ezebilirsin, programla geleni de kendi
kopyanla değiştirebilirsin.

Beşincisi paketin **içinde** durur; kurulumda kopyalanması ya da sembolik bağ
kurulması gerekmez ve hangi dizinde çalıştığın önemli değildir. Sebep ölçüldü:
depo `/root/aider`'a klonlanıp `/root/aider-work` içinde çalışılınca ilk dört
kökün hiçbiri eşleşmiyor ve program "Beceriler: 0 yüklendi" diyordu.

### Otomatik tetikleme

Beceriyi yüklemek için modelin `Skill` aracını çağırmasını beklemiyoruz.
Ölçüldü: 14 beceri yüklüyken `gemma4:e4b`, "skyup sunucusuna bağlan ve OS
güncel mi diye bak" isteğinde `Skill`'i **bir kez bile çağırmadı**. Katalog
sistem promptunda duruyor ama 4B sınıfı bir model onlarca satırdan doğru
olanı seçemiyor.

Bunun yerine eşleştirme deterministik: isteğin metni becerilerin tetikleyici
ifadeleriyle karşılaştırılır, en isabetli **tek** beceri o turun bağlamına
eklenir ve ekrana `Beceri otomatik yüklendi: ansible (ansible)` yazılır.

Tetikleyiciler `description` alanındaki tırnak içi ifadelerden okunur —
37 becerinin hepsi zaten böyle yazılmış. Ezmek istersen frontmatter'a:

```yaml
triggers: hammer, content view, capsule
auto: false        # bu beceri hiç otomatik yüklenmesin
```

Eşleşme Türkçe karakterleri katlar (`bağlanamıyor` = `baglanamiyor`) ve ek
almış kelimeleri tutar (`playbook'u`, `ansible'da`); kelime **ortasında**
eşleşmez, yani `paramount` içindeki `mount` tetiklemez.

Sıralama: kaç ayrı tetikleyici tuttuğu > becerinin kendi adının geçmesi
(+ağırlık) > en uzun eşleşme > az konu iddia eden beceri. Ad ağırlığı olmadan
genel bir ifade (`"kontrol et"`) becerinin adını (`"ansible"`) geçiyordu.

Hangi becerinin tetikleneceğini modeli çalıştırmadan sınamak için:

```
/skills tetik disk doldu, kim yiyor?
```

Kapatmak için `--no-auto-skills`.

### Programın kendi yardımından beceri üretme

Çevrimdışı bir model bilmediği aracın sözdizimini arayamaz, uydurur.
`/beceri-uret` referansı aracın kendisinden toplar:

```
/beceri-uret hammer --host satellite --ad satellite-hammer
```

`<program> --help` ağacını gezer (alt komutlar dahil), ham çıktıyı
`aider-skills/<ad>/referans/yardim.md` dosyasına yazar, `SKILL.md` iskeletini
oluşturur ve gövdeyi doldurma işini modele devreder. Model komutları
hafızadan değil bu referanstan alır.

`--host` verirsen program uzak sunucuda aranır; sunucu adı `~/.ssh/config`'e
karşı doğrulanır. Var olan bir `SKILL.md`'nin üstüne yazılmaz, yalnızca
referans tazelenir.

Yeni beceri oluşturmak için `/skills new <ad>` — iskeleti `aider-skills/`
altına, yani depoya girebilen konuma yazar. `/skills` ile diskten yeniden
yükleyip aider'ı kapatmadan test edersin.

Depodaki `aider/beceriler/kod-inceleme` ve `aider/beceriler/test-yaz` çalışan
örneklerdir; kendi becerini yazarken biçim referansı olarak kullan.

## İzin sistemi

Üç mod var:

```bash
aider --agent            # ask  — yan etkili her araçta sorar (varsayılan)
aider --agent --auto     # auto — reddedilmedikçe sormaz
aider --agent --plan     # plan — Write/Edit/Bash modele hiç sunulmaz
```

Asıl işi kural listesi yapar. `.aider/permissions.yml`:

```yaml
mode: ask

allow:
  - Bash(git diff:*)      # "git diff" ile başlayan komutlar
  - Bash(pytest:*)
  - Bash(npm test)        # tam olarak bu komut
  - Write(src/**)         # src altına yazma
  - Edit(*.py)

deny:
  - Bash(npm publish:*)
  - Bash(kubectl delete:*)

ask:
  - Bash(dnf install:*)
  - Bash(systemctl restart:*)
```

Üç katman var ve sırası şu:

| Katman | Anlamı | `auto` modda | Kullanıcı `allow` ile ezebilir mi |
|---|---|---|---|
| `deny` | Asla çalışmaz | engellenir | hayır |
| `ask` | Sorulur, onaylanırsa çalışır | **sorulur** | evet |
| `allow` | Sorulmadan çalışır | çalışır | — |

`ask` katmanı "özel olarak söylenmedikçe yapılmasın, söylenirse yapılsın"
gereksinimi içindir. `reboot` bunun tipik örneğidir: oto modda kendiliğinden
sunucu yeniden başlatılmaz, ama sen istersen onaylayıp çalıştırırsın.

Kurallar iki dosyadan birleştirilir: `~/.aider/permissions.yml` (kişisel) ve
`<proje>/.aider/permissions.yml` (projeye özgü). Komut satırındaki
`--permission-mode` dosyadaki modu yener.

Oturum içinde bir komuta "bir daha sorma" dersen, o çağrı bir kurala çevrilip
oturumluk izin listesine eklenir. `/permissions` ile o anki kuralları görürsün.
Kalıcı yapmak için dosyaya yazman gerekir.

### Kaçış vektörleri kapalı

İzin sistemi bir güvenlik sınırı olduğu için şu üç yol kasıtlı olarak tıkandı:

- **Zincirleme.** `git diff && npm publish` komutunda her parça ayrı ayrı
  değerlendirilir. `Bash(git diff:*)` kuralı bu komutu onaylamaz.
- **Komut ikamesi.** `$(...)`, backtick ve `<(...)` içeren komutlar statik
  olarak çözülemediği için hiçbir zaman otomatik onaylanmaz.
- **Sözcük sınırı.** `Bash(git diff:*)` kuralı `git diff-tree` komutunu
  kapsamaz; önek eşleşmesi boşlukta durur.

### Yerleşik listeler

**Asla çalışmaz** (`allow` ile bile açılamaz): `rm -rf /*`, `rm -rf ~*`,
`mkfs*`, `dd if=*`. Geri alınamaz ve felaketle sonuçlanır.

**Oto modda bile sorulur** (ama `allow` ile açılabilir):

| Kalıp | Neden |
|---|---|
| `reboot`, `shutdown`, `init` | makineyi kapatır |
| `sudo`, `doas` | yetki yükseltir |
| `git push`, `git reset --hard`, `git clean -fdx` | geri alınamaz ya da dışarı çıkar |
| `sh`, `bash`, `zsh` (tam eşleşme) | `curl ... \| sh` kalıbının kabuk parçası |
| `ansible-playbook`, `ansible` | **`--limit` yoksa envanterin tamamına dokunur** |
| `dnf/yum install\|remove\|update`, `systemctl stop\|restart\|disable` | üretimde kesinti |

Son iki satır tek makineyi değil filoyu ilgilendiriyor: oto modda tek bir
araç çağrısı yüzlerce sunucuyu değiştirebilirdi. Salt-okunur karşılıkları
(`dnf list`, `systemctl status`, `systemctl is-active`, `ansible-inventory`,
`ansible-doc`) kapsam dışı — önek eşleşmesi sözcük sınırı aradığı için
`ansible-doc`, `ansible` kuralına takılmıyor.

### Uzak komutlarda sunucu kapsamı

`::` sunucu kapsamını komut deseninden ayırır; sunucu kısmı glob'dur:

```yaml
allow:
  - Ssh(skyup::systemctl restart:*)   # yalnızca skyup'ta
  - Ssh(test-*::uptime)               # adı test- ile başlayan sunucularda
```

`::` yoksa kural **her sunucuda** geçerlidir. Reddetme kurallarında istenen
budur; izin kurallarında ise fazla geniştir — test sunucusunda onayladığın
komut üretimde de onaysız çalışırdı.

Bu yüzden bir uzak komutta "bir daha sorma" dediğinde üretilen kural hem
komuta hem sunucuya daralır:

```
Ssh(skyup::yum check-update:*)
```

### Uzak komutlar da kapsanır

`Bash(...)` biçiminde yazılmış **reddetme ve sorma** kuralları `Ssh` ile
gönderilen komutlara da uygulanır. Aksi hâlde `rm -rf /` yerelde yasakken
sunucuda serbest kalırdı.

Genişletme tek yönlüdür: `Bash(uptime:*)` **izni** `Ssh`'a geçmez. Reddi
genişletmek güvenli tarafa düşer, izni genişletmek düşmez. Uzak komuta izin
vermek istiyorsan kuralı açıkça `Ssh(uptime:*)` diye yaz.

## MCP

Claude Code ile aynı `.mcp.json` biçimi kullanılır — mevcut dosyalarını
doğrudan kopyalayabilirsin:

```json
{
  "mcpServers": {
    "postgres": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres"],
      "env": {"DATABASE_URL": "postgres://..."}
    }
  }
}
```

Sunucular oturum başında başlatılır, araçları `mcp__<sunucu>__<araç>` adıyla
modele sunulur ve oturum bitince süreçler kapatılır.

| Komut | Ne yapar |
|---|---|
| `/mcp` | Bağlı sunucuları ve araçlarını listeler |
| `/mcp reload` | Sunucuları durdurup yeniden başlatır |

Sunucunun `readOnlyHint` verdiği araçlar onay sorulmadan çalışır; geri kalanı
izin sisteminden geçer.

**Dayanıklılık:** bir sunucunun başlatılamaması oturumu düşürmez — hata
bildirilir, diğer sunucularla devam edilir. Yanıt vermeyen sunucu zaman aşımına
uğrar; istemci arka planda okuyan bir iş parçacığı kullandığı için bloke olmaz.

## Plan modu

```bash
.venv/bin/aider --agent --plan
```

Plan modunda `Write`, `Edit` ve `Bash` araçları modele **hiç sunulmaz** — model
onları çağırmayı deneyemez bile. Yalnızca `Read`, `Grep`, `Glob` ve `Skill`
kullanılabilir.

Model araştırmasını bitirince `ExitPlanMode` ile planını sunar. Sen onaylarsan
plan modu kapanır ve uygulama başlar; onaylamazsan model plan modunda kalır ve
planı revize eder.

Oturum içinde `/plan` ile açıp kapatabilirsin.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `/agent` | Agent moduna geçer |
| `/plan` | Plan modunu açar/kapatır |
| `/skills` | Becerileri listeler ve diskten yeniden yükler |
| `/skills new <ad>` | Yeni beceri iskeleti oluşturur |
| `/skills tetik <istek>` | O istek hangi beceriyi tetiklerdi, gösterir |
| `/oturumlar` | Önceki agent oturumlarını listeler |
| `/beceri-uret <program>` | Programın `--help` ağacından beceri + komut referansı üretir |
| `/mcp` | MCP sunucularını ve araçlarını listeler |
| `/mcp reload` | MCP sunucularını yeniden başlatır |
| `/permissions` | İzin modunu ve kurallarını gösterir |
| `/todo` | Mevcut görev listesini gösterir |
| `/model <ad>` | Modeli değiştirir (aider'ın kendi komutu) |
| `/model-ekle` | Yeni modeli adım adım tanımlar ve kaydeder |
| `/voice` | Mikrofondan kayıt alıp metne çevirir (bkz. Ses girişi) |

`/skills` beceriyi yeniden okuduğu için, `SKILL.md` dosyasını düzenleyip aider'ı
yeniden başlatmadan test edebilirsin.

## Ses girişi (`/voice`)

Upstream aider'da hazır gelen bir özellik; fork bunu değiştirmedi. Mikrofondan
kayıt alır, metne çevirir ve **prompt'a yazar** — komutu senin yerine
çalıştırmaz, yazdığın yere metni koyar, sen Enter'a basarsın.

```
/voice
```

| Bayrak | Ne yapar |
|---|---|
| `--voice-format` | Kayıt biçimi (`wav` varsayılan; `mp3`, `webm` ffmpeg ister) |
| `--voice-language` | ISO 639-1 dil kodu, örn. `tr`. Verilmezse otomatik. |
| `--voice-input-device` | Giriş aygıtı adı |

Türkçe için `--voice-language tr` vermek doğruluğu belirgin biçimde artırır.

### Bağımlılıklar

`sounddevice`, `soundfile`, `numpy` ve sistem tarafında **portaudio** gerekir.
Bu geliştirme makinesinde dördü de kurulu (ölçüldü). RHEL'de:

```bash
dnf install portaudio                 # sistem kütüphanesi
pip install sounddevice soundfile     # çevrimdışıysa wheel taşı
```

Sunucuda mikrofon olmadığı için `/voice` pratikte **yerel makinede** anlamlı.

### Kurumsal ortam için kritik uyarı

`aider/voice.py` çeviriyi şöyle çağırıyor:

```python
transcript = litellm.transcription(model="whisper-1", file=fh, ...)
```

İki nokta önemli:

1. **Model adı `whisper-1` olarak sabit yazılmış.** Kurum endpoint'inde bu adla
   bir model yoksa çalışmaz.
2. **`api_base` ve `api_key` hiç geçirilmiyor.** `litellm.transcription` bu iki
   parametreyi kabul ediyor (doğrulandı) ama aider vermiyor; adres yalnızca
   `OPENAI_API_BASE` ortam değişkeninden çözülüyor.

Sonucu şu: **`OPENAI_API_BASE` boşsa ses kaydın `api.openai.com`'a gider.**
Sohbet tarafındaki sessiz yönlenme tuzağının aynısı, ama bu sefer giden şey
sesin. Banka ortamında bu, verinin kurumdan çıkması demektir.

Bu yüzden `/voice` kullanmadan önce:

```bash
echo "$OPENAI_API_BASE"      # boş dönerse /voice KULLANMA
```

Kurum endpoint'i `/v1/audio/transcriptions` uç noktasını sunmuyorsa `/voice`
zaten hata verecektir — sessizce dışarı gitmesindense hata alması iyidir.
Endpoint'in bu ucu destekleyip desteklemediği:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST "$OPENAI_API_BASE/audio/transcriptions" \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

`404` → uç yok, `/voice` çalışmaz. `400` → uç var, eksik parametreden şikâyet
ediyor demektir.

Ses girişini kurum içinde tutmanın alternatifi yerel bir Whisper sunucusu
(`faster-whisper` OpenAI uyumlu bir uç sunabiliyor) ve `OPENAI_API_BASE`'i
ona yöneltmektir. Bu fork'ta denenmedi.

## Bayraklar

| Bayrak | Varsayılan | Ne yapar |
|---|---|---|
| `--agent` | — | Agent moduna geçer (`--edit-format agent` ile aynı) |
| `--plan` | `false` | Plan modunda başlar |
| `--auto` | — | `--permission-mode auto` kısayolu |
| `--permission-mode MOD` | `ask` | `plan`, `ask` ya da `auto` |
| `--max-tool-iterations N` | `50` | Tek mesajda izin verilen azami model turu |

`--max-tool-iterations` bir emniyet sübabıdır: model araç döngüsünde takılıp
kalırsa sınıra ulaşıldığında durur ve uyarı basar.

## Mimari

```
aider/agent/
  registry.py     ToolRegistry + ToolContext + ToolError
  tools.py        Read, Write, Edit, Bash, Glob, Grep
  permissions.py  Kural tabanlı izin sistemi
  mcp.py          MCP istemcisi (stdio, JSON-RPC 2.0)
  skills.py       SKILL.md keşfi, frontmatter ayrıştırma, Skill aracı
  todo.py         Görev listesi + TodoWrite aracı
  plan.py         Plan modu + ExitPlanMode aracı

aider/coders/
  agent_coder.py     Araç döngüsü (AgentCoder)
  agent_prompts.py   Sistem promptu
```

Upstream aider dosyalarına dokunuş bilinçli olarak minimumda tutuldu:

- `models.py` — `send_completion` artık iki tool biçimini de destekliyor.
  Upstream sürüm `tool_choice`'u tek bir fonksiyona **zorluyordu**; agentic
  döngü için model araçlar arasından kendisi seçebilmeli. Önceden sarmalanmış
  `{"type": "function", ...}` listesi gelirse `tool_choice="auto"` kullanılır,
  eski çıplak şema listesi gelirse davranış aynen korunur.
- `coders/__init__.py` — `AgentCoder` kaydı
- `args.py` — `--agent`, `--plan`, `--max-tool-iterations`
- `main.py` — agent'a özgü kwarg'ların yalnızca agent coder'a geçirilmesi
- `commands.py` — `/agent`, `/plan`, `/skills`, `/mcp`, `/permissions`, `/todo`

Bu ayrım kasıtlıdır: upstream aider'dan `git merge` yaptığında çakışma yüzeyi
beş küçük noktayla sınırlı kalır.

### Araç hataları neden istisna değil?

`ToolRegistry.run` hiçbir zaman istisna sızdırmaz; her hatayı modele geri
verilebilir bir metne çevirir. Model yanlış argüman gönderdiğinde ya da olmayan
bir dosyayı okumaya çalıştığında oturum çökmez — model hatayı görür ve kendini
düzeltir. Bu, agentic döngünün dayanıklılığının temelidir.

## Upstream'den güncelleme

Fork upstream aider'ın beş dosyasına dokunuyor. Merge'in asıl riski çakışma
değil — çakışma görünür. Asıl risk merge'in yama satırlarını koruyup
**davranışı** bozmasıdır.

```bash
./scripts/upstream_birlestir.sh              # en son upstream main
./scripts/upstream_birlestir.sh v0.90.0      # belirli bir etiket
```

Betik upstream'i getirir, dokunduğumuz dosyalarda ne değiştiğini gösterir,
merge eder, fork değişmezlerini doğrular ve testleri çalıştırır. Çakışmayı
çözmez — kararı sana bırakır.

Elle merge yaptıysan:

```bash
.venv/bin/python scripts/fork_dogrula.py
```

Bu betik dokuz değişmezi **kodu çağırarak** sınar, dosyada metin aramaz. Bir
merge `models.py`'deki yama satırlarını koruyup `tool_choice`'u yine
sabitleyebilir; metin araması bunu kaçırır, davranış testi kaçırmaz.

Bozulan her kontrol hangi dosyaya bakman gerektiğini ve o dokunuşun neden
orada olduğunu söyler.

## Testler

```bash
.venv/bin/python -m pytest tests/basic/test_agent.py -q
```

127 test:

- **Araçlar** — her aracın mutlu yolu ve hata yolları
- **Beceriler** — keşif, frontmatter ayrıştırma, kök öncelik sırası
- **Görev listesi** — doğrulama kuralları
- **Plan modu** — yan etkili araçların gerçekten sunulmadığı
- **Araç döngüsü** — sahte modelle uçtan uca: çoklu araç çağrısı, bozuk JSON,
  bilinmeyen araç, döngü sınırı
- **İzinler** — kural eşleşmesi ve üç kaçış vektörü (zincirleme, komut ikamesi,
  sözcük sınırı); ayrıca yerleşik deny listesinin normal komutları
  engellemediği
- **MCP** — gerçek alt süreçlerle: el sıkışma, araç keşfi, çağrı gidiş-dönüşü,
  çöken sunucu, yanıt vermeyen sunucu (zaman aşımı gerçekten uygulanıyor mu),
  bir sunucunun ölümünün diğerlerini etkilemediği

- **Model tanımlama** — `/model-ekle` akışı: önek, izinler, üzerine yazma
- **Beceriler** — depodaki 37 becerinin yüklenebildiği ve tetikleme
  açıklamalarının var olduğu

Ayrıca `scripts/fork_dogrula.py` fork değişmezlerini davranışsal olarak sınar.

Tüm upstream test takımı da geçmeye devam eder (toplam 602 test).
