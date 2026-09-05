# aider-agent

Bu depo [Aider-AI/aider](https://github.com/Aider-AI/aider)'ın forkudur. Amaç
aider'ı geliştirmek değil, **kurum içi Qwen endpoint'inde çalışan, Claude Code
benzeri bir ajana dönüştürmek**.

Fork noktası: upstream `5dc9490`.

## Kapsam filtresi

Sahibinin fiilen kullandığı ve geliştirilmesini istediği özellikler:

1. Plan modu ve auto mod
2. Model ekleyebilmek (kurum endpoint'i + yerel modeller)
3. İzin sisteminin yolda durmaması
4. MCP ve beceri geliştirme

**Bu listede olmayan bir özelliği kendiliğinden ekleme.** Subagent, hooks ve web
araçları bilinçli olarak kapsam dışı bırakıldı. Claude Code'da var diye bir şeyi
buraya taşımak gerekçe değildir.

## Mimari

Agent katmanı ayrı bir pakette; `base_coder.py`'ye ameliyat yapılmadı.

```
aider/agent/
  registry.py     ToolRegistry, ToolContext, ToolError
  tools.py        Read, Write, Edit, Bash, Glob, Grep
  ssh_tool.py     Ssh — adı ssh config, known_hosts ve ansible envanterinde arar
  permissions.py  Üç katmanlı izin sistemi (deny / ask / allow)
  mcp.py          MCP istemcisi (stdio, JSON-RPC 2.0)
  skills.py       SKILL.md keşfi ve kademeli açılım
  beceri_uret.py  Programın --help ağacından beceri + referans üretimi
  todo.py         Görev listesi
  plan.py         Plan modu
  model_setup.py  /model-ekle akışı
  oturum.py       Oturum kaydı (JSONL) ve --continue ile geri yükleme
  sikistirma.py   Bağlam özeti (/ozet) ve otomatik sıkıştırma
  glyph.py        Terminal Unicode taşımıyorsa ASCII'ye düşme
  yapistirma.py   Uzun yapıştırmayı prompt'ta yer tutucuya indirme

aider/coders/
  agent_coder.py     Araç döngüsü
  agent_prompts.py   Sistem promptu
```

### Upstream'e dokunulan sekiz nokta

Çakışma yüzeyi bilinçli olarak buraya sınırlandı. Bir upstream dosyasını
değiştirmek zorunda kalırsan yamayı en küçük blokta tut ve nedenini yorumda yaz.

| Dosya | Ne yapıldı |
|---|---|
| `aider/models.py` | `send_completion` çok araçlı `tool_choice="auto"` destekliyor; `ModelInfoManager.set_offline()` |
| `aider/coders/__init__.py` | `AgentCoder` kaydı |
| `aider/args.py` | `--agent`, `--plan`, `--auto`, `--permission-mode`, `--max-tool-iterations`, `--offline`, `--auto-skills`, `--auto-compact`, `--continue` |
| `aider/main.py` | Agent kwarg'ları yalnızca agent coder'a; repo map agent modunda kapalı; `--offline` zorlaması; coder değişiminde agent kancalarının bırakılması |
| `aider/io.py` | Mod göstergesi kancaları, `shift+tab`, çıktı ASCII süzgeci, yapıştırma yer tutucusu |
| `aider/commands.py` | On dört slash komutu; `/voice` çevrimdışı modda kapalı |
| `.gitignore` | `.env` ve `.mcp.json` ignore |
| `README.md` | Fork'un kendi ön yüzü; upstream'inki `ORIJINAL-README.md` |

En kritik olanı `models.py`: upstream `tool_choice`'u **tek bir fonksiyona
zorluyordu**, bu da agentic döngüyü imkânsız kılıyor.

## Modelsiz uçtan uca sınama

`scripts/sahte_endpoint.py` OpenAI uyumlu bir sahte sunucu. Agent döngüsünün
doğruluğu modelin zekâsına bağlı değil: araçlar çalışıyor mu, `tool_calls`
yanıtsız kalıyor mu, istek pencereye sığıyor mu — hiçbiri için gerçek model
gerekmiyor, ama kullanıcının fiilen çarptığı hatalar bunlar.

Sunucu senaryodaki yanıtları sırayla döndürür **ve gelen isteği denetler**:
yanıtsız `tool_call`, eşleşmeyen `tool` yanıtı, pencereyi aşan istek. Üçüncüsü
srvsatellite'te yaşananın ta kendisi (16385 token / sınır 16384). Aşılırsa
gerçek endpoint gibi 400 döner.

Akış (SSE) destekliyor ve bu önemli: aider varsayılan olarak `stream=true`
gönderiyor, yani üretimde çalışan kod yolu `_consume_stream`. Yalnızca akışsız
sınamak, asıl yolu hiç sınamamak demek.

```bash
venv/bin/python scripts/sahte_endpoint.py --port 8000 --pencere 16384 \
  --senaryo 'Read:{"file_path":"envanter.ini"} | metin:Okudum.' &
aider --agent --model openai/sahte-model --openai-api-base http://127.0.0.1:8000/v1
```

skyup'ta (AlmaLinux 10, Python 3.12) 800 satırlık envanterle çalıştırıldı.
Beş ardışık okuma isteği 4.299 → 8.583 → 12.884 token büyüttü, sonra kırpma
devreye girip 13.252 → 13.632 → 14.023'te tuttu. Altı isteğin hiçbiri 16.384'ü
aşmadı, hiçbirinde yetim `tool_call` çıkmadı ve iş yarıda kalmadı.

### Canlı senaryo matrisi

Birim testleri döngüyü sonuna kadar götürmüyor; iki hata yalnızca programı
gerçekten çalıştırınca çıktı. Sahte endpoint'e karşı şunlar canlı sınandı
(skyup, AlmaLinux 10):

| Senaryo | Sonuç |
|---|---|
| 800 satırlık dosyayı sayfa sayfa okuma | 6 sayfa, devam offset'i doğru |
| Pencereyi taşıran beş ardışık okuma | kırpma tuttu, iş yarıda kalmadı |
| Araç hatası (olmayan dosya) | döngü toparlandı, ikinci araca geçti |
| Bash | komut gerçekten çalıştı |
| Plan modunda `Write` | dosya oluşmadı; **ekranda görünmüyordu — düzeltildi** |
| Oturum kaydı + `--continue` | `tool_calls` korundu, yetim çağrı çıkmadı |
| 7k pencerede dört tur | büyüme 4.425 → 4.984'te düzleşti |

**Ölçünün kendisi de yanılabilir.** Sahte endpoint önce token'ı karakter/2 ile
tahmin ediyordu; pencereye rahat sığan bir isteği "aşıyor" gösterdi ve olmayan
bir hata arandı. Artık gerçek tokenizer (tiktoken) kullanıyor. Test düzeneğinin
ölçüsü yanlışsa düzenek zararlı.

## Komutlar

```bash
.venv/bin/python -m pytest tests/basic -q          # tüm testler (~585)
.venv/bin/python -m pytest tests/basic/test_agent.py -q   # agent testleri (~130)
.venv/bin/python scripts/fork_dogrula.py           # fork değişmezleri
.venv/bin/python -m flake8 aider/ tests/basic/test_agent.py
.venv/bin/python -m black --line-length 100 --preview aider/agent/
```

`tests/basic/test_sendchat.py` ağa çıkmaya çalışır; tek başına geçer.

## Kod kuralları

- **Satır uzunluğu 100.** `.flake8` ve `.pre-commit-config.yaml` bunu dayatıyor.
- **Yorumlar ve kullanıcıya görünen metinler Türkçe.** Upstream kodun İngilizce
  yorumlarına dokunma; yeni yazdığın agent katmanı Türkçe.
- Docstring'ler *neden*i anlatsın, *ne*yi değil. Kod ne yaptığını zaten söylüyor.
- Yeni yetenek eklerken önce `aider/agent/` içinde bir araç ya da modül olarak dene.

## Bu depoda üç tuzak var

Üçü de bu projede fiilen yaşandı ve teşhisi zaman aldı.

### 1. `.gitignore` — negasyon kullanma

Aider'ın `--add-gitignore-files` özelliği `.gitignore` sonuna kendi `.aider*`
satırını **ekliyor**. Gitignore'da son eşleşen kural kazandığı için, `.aider/`
altındaki dosyaları depoya sokmak üzere yazılan `!` negasyonları sessizce
etkisiz kalıyor — hata verilmeden, dosyalar commit'e girmeyerek.

Bu yüzden depoya girmesi gereken hiçbir şey `.aider` ile başlayan bir dizinde
durmuyor:

- `ornek/` — yapılandırma şablonları
- `ornek/altyapi/` — filo şablonu

Programla gelen 37 beceri ise paketin içinde: `aider/beceriler/`. Orada
durmasının sebebi ayrı — hangi dizinde çalışılırsa çalışılsın görünsünler.

`.gitignore`'a `!` ile başlayan satır ekleme. Bir dosyanın gerçekten depoya
girdiğini `git ls-tree -r <dal> --name-only` ile doğrula; `git status` yeterli
değil.

### 2. `litellm`'i testte elle yamalama

`aider.llm.litellm` tembel yükleyici bir proxy. Testte
`models_mod.litellm.completion = fake` diye atama yapmak proxy üzerinde kalıcı
iz bırakıyor ve `finally` ile geri yazsan bile sonraki testlerdeki
`@patch("litellm.completion")` bozuluyor.

Belirti: testler tek başına geçiyor, birlikte çalıştırılınca `test_sendchat.py`
gerçek ağa çıkıp `InternalServerError: Connection error` veriyor.

Her zaman `with patch("litellm.completion", ...)` kullan.

### 3. `git check-ignore` izlenen dosyaları atlar

Bir desenin gerçekten eşleşip eşleşmediğini sınamak için `--no-index` şart.
Onsuz komut, izlenen dosyalar için desen eşleşse bile "ignore edilmiyor" der.
`scripts/fork_dogrula.py` bu yüzden bir süre bozulmayı hiç yakalayamadı.

## Upstream'den güncelleme

`git merge` yaptıktan sonra **mutlaka**:

```bash
.venv/bin/python scripts/fork_dogrula.py
```

Bu betik fork'un sekiz dokunuş noktasının hâlâ **çalıştığını** doğrular — dosyada
metin aramaz, kodu gerçekten çağırır. Bir merge yaman satırları koruyup
davranışı bozabilir; metin araması bunu kaçırır.

Tüm yordamı otomatik yürüten sarmalayıcı:

```bash
./scripts/upstream_birlestir.sh              # en son upstream main
./scripts/upstream_birlestir.sh v0.90.0      # belirli bir etiket
```

Ayrıntılı yordam, her dokunuş noktasının tam yaması ve çakışma çözme rehberi:
**`BIRLESTIRME.md`**. Aylar sonra okuyacak kişi için yazıldı; yamaları elle
geri koyabilecek kadar ayrıntılı.

## Model ekleme ve yapılandırma dosyaları

`/model-ekle` tek soru soruyor: endpoint adresi. Adres normalize ediliyor —
şema eksikse `http://` ekleniyor, `/v1` yoksa ekleniyor, sonda kalmış
`/models` ya da `/chat/completions` kırpılıyor. Sonra `/v1/models` çekiliyor,
model listeden seçiliyor, pencere yanıttan okunuyor, araç desteği küçük bir
istekle deneniyor.

Anahtar ancak liste anahtarsız alınamazsa soruluyor. Boş adres artık
reddediliyor: eskiden varsayılana düşüyordu ve adressiz yapılandırma sessizce
`api.openai.com`'a gidiyor — hava boşluklu ortamda bu sessiz bir sızıntı.

**"Endpoint tipi" sorusu kaldırıldı.** Üç seçenek de (kurum / ollama / yerel)
aynı litellm sağlayıcısını, `openai/`, kullanıyordu; soru yalnızca hangi
varsayılan adresin doldurulacağını seçiyordu. Kullanıcı zaten adresi
yazacaksa karşılığı yok.

Üç yapılandırma dosyası **aider'ın kendi tasarımı**, fork'un icadı değil:

| Dosya | Kim okuyor | Neden ayrı |
|---|---|---|
| `~/.aider.conf.yml` | aider CLI | Komut satırı varsayılanları (YAML sözlük) |
| `~/.aider/model.settings.yml` | aider model katmanı | Model başına edit_format, sıcaklık (YAML **liste**) |
| `~/.aider/model.metadata.json` | litellm | Pencere ve maliyet (**JSON** sözlük) |

Üçü farklı biçimde ve farklı tüketiciye ait olduğu için tek dosyada
birleştirilemiyorlar. Ama tek dizinde toplanabiliyorlar: conf dosyası
`model-settings-file` ve `model-metadata-file` ile diğer ikisini gösteriyor,
ikisi de `~/.aider/` altında. `~/.aider.conf.yml` yerinde kalmak zorunda —
aider'ın kendiliğinden bulduğu giriş noktası orası.

**Her model kendi endpoint'ini taşıyor.** `conf`'taki `openai-api-base` tek ve
geneldir; ikinci model eklenince üzerine yazılıyor. İkinci model başka bir
sunucudaysa (kurum vLLM'i + yerel Ollama gibi) `/model` ile birinciye dönmek
istekleri SESSİZCE ikincinin sunucusuna yolluyordu. Adres ve anahtar artık
model ayarına da `extra_params` olarak yazılıyor; `send_completion` bunu
litellm çağrısına doğrudan aktarıyor. Anahtar taşıdığı için ayar dosyası da
0600 yazılıyor.

Eski konumdaki (`~/.aider.model.*`) tanımlar yeni dosyaya taşınıyor.
**Eski dosya silinmedikçe okunmaya devam ediyor** — `generate_search_path_list`
varsayılan adı her zaman arama listesine koyuyor. Zarar vermiyor çünkü liste
ters çevriliyor ve conf'un gösterdiği dosya en sona, yani üste düşüyor; ama
"artık okunmuyor" demek yanlış olur. `TestAyarDosyasiSirasi` bu sırayı koruyor:
sıra bozulursa `/model-ekle` ile tanımlanan model sessizce eski ayarlarla
çalışır.

## Beceriler

Programla birlikte 37 beceri geliyor (`aider/beceriler/`). Agent modunda model bunları
kendiliğinden yükler; sen de referans olarak okuyabilirsin.

| Beceri | Ne zaman |
|---|---|
| `kod-inceleme` | Değişiklik gözden geçirme |
| `guvenlik-incelemesi` | Güvenlik açığı arama |
| `sadelestir` | Tekrar ayıklama, ölü kod temizliği |
| `hata-ayikla` | Hata ve çöken test araştırması |
| `test-yaz` | Test yazma |
| `beceri-yaz` | Yeni beceri yazma |
| `beceri-gelistir` | Var olan beceriyi gerçek sunucuda doğrulayıp düzeltme |
| `mcp-ekle` | MCP sunucusu ekleme, teşhis, çevrimdışı kurulum |
| `upstream-birlestir` | Upstream'den güncelleme |
| `rhel-yonetim` | RHEL sistem yönetimi, Satellite, IdM |
| `sistem-guncelleme` | dnf, güvenlik yaması, yeniden başlatma kararı |
| `ansible` | Envanter doğrulama, ad-hoc, playbook, kuru çalıştırma |
| `filo-durum-kontrolu` | Aynı kontrolü tüm filoda çalıştırıp sapanı bulma |
| `ag-teshis` | Ağ, güvenlik duvarı, DNS, port erişimi |
| `selinux` | AVC okuma, boolean, port etiketi, dosya bağlamı |
| `depolama` | Disk dolması teşhisi, inode, yeri kim yiyor |
| `disk-ekleme` | LVM ve düz bölüm büyütme, XFS, fstab |
| `nfs-mount` | NFS paylaşımı, fstab seçenekleri, asılı mount |
| `sunucu-teslim` | Devralma, Satellite kaydı, güncelleme, teslim |
| `satellite-yonetim` | hammer ping, içerik görünümü, depo senkronu |
| `rhel-surumleri` | RHEL 7/8/9/10 komut ve yapılandırma farkları |
| `solaris-ldom` | Solaris 11 ve LDOM — keşif yordamı, doğrulanmadı |
| `guvenlik-ajani` | SEP / Cortex XDR keşif yordamı |
| `idm-yonetim` | IdM/FreeIPA istemci kurulumu, Kerberos, SSSD |
| `sssd-adtrust` | AD trust hesapları login olamıyor — runbook |
| `splunk-forwarder` | Forwarder takıldı, log akmıyor — runbook |
| `performans` | Yük, CPU/bellek/disk darboğazı, log okuma |
| `k8s-rancher` | Kubernetes/Rancher teşhisi |
| `podman-docker` | Tek makinede konteyner: podman/docker, rootless, compose |
| `nexus-registry` | Kurum registry'si: login, pull/push, save/load ile taşıma |
| `servis-teshis` | PostgreSQL, Redis, RabbitMQ — konteyner tespiti dahil |
| `web-sunucu` | Nginx, Apache, 502/504, SELinux |
| `sertifika-tls` | openssl: süre, SAN, zincir, kurumsal CA, starttls |
| `rapor-uret` | Biçim seçimi, CSV ve HTML (bağımlılıksız) |
| `rapor-excel-pdf` | xlsx ve PDF: bağımlılık, font, çevrimdışı kurulum |
| `git-azuredevops` | Git, PR, pipeline, merge çakışması |
| `belge-yaz` | README, runbook, mimari notu |

`ornek/altyapi/` altında filo geneli operasyonlar için ayrı bir şablon var
(beceri + izin kuralları). Aider fork'unun parçası değil, kopyalanacak örnek.

Yeni beceri: `/skills new <ad>` — iskeleti `aider-skills/` altına yazar.
Var olan bir programdan beceri: `/beceri-uret <program> [--host <sunucu>]` —
aracın `--help` ağacını gezip ham çıktıyı `referans/yardim.md`'ye yazar,
gövdeyi model doldurur. Çevrimdışı modelin komut uydurmasına karşı.

## Ses girişi

`/voice` upstream'den geliyor, fork dokunmadı. İki tuzağı var ve ikisi de
sessiz: `aider/voice.py` model adını `whisper-1` olarak sabit yazıyor ve
`litellm.transcription`'a `api_base` geçirmiyor — parametre kabul ediliyor
ama verilmiyor. Dolayısıyla `OPENAI_API_BASE` boşsa **ses kaydı
`api.openai.com`'a gider**. Ayrıntı ve kontrol yordamı `AGENT.md`'de.

## Terminal kodlaması

Kurum terminalleri her zaman UTF-8 değil ve tek bir karakter satırı bozuyor:
kullanıcı `→ Grep(...)` yerine `?? Grep(...)`, prompt'ta da mod işareti yerine
boş kutu görüyor.

İki ayrı sorun var ve karıştırılmamalı. Birincisi kodlama: `LANG=C` ya da
tanımsız yerel ayar. `aider/agent/glyph.py` bunu sezip metni ASCII'ye çeviriyor
— Türkçe harfler soru işaretine değil, harf çevirisine gidiyor (`sonuç` →
`sonuc`), yoksa metin okunmaz oluyor. Süzgeç `io.py`'de, çıkış noktasında:
agent katmanındaki otuz ayrı çağrıyı tek tek sarmalamak yerine.

İkincisi font: yerel ayar UTF-8 dese bile terminalin fontunda glyph
olmayabiliyor ve sezgi bunu göremez. Bu yüzden mod işaretleri Claude Code'un
kullandığı U+23F5/U+23F8'den Geometric Shapes bloğuna (`▶`, `▮▮`) taşındı —
kutu çizgisi olan hemen her fontta var. Yine de bozuksa iki yönlü elle anahtar
var: `AIDER_ASCII=1` ve `AIDER_UNICODE=1`.

Yerel ayar tanımsızsa artık ASCII'ye düşülüyor. Eskiden "karar veremiyorum"
diye Unicode basılıyordu; `LANG`'siz bir ssh oturumu genellikle UTF-8 değil.

## Yapıştırma

300 satırlık bir log yapıştırıldığında prompt o 300 satırı çiziyor, ekran
kayıyor ve kullanıcı ne yazdığını göremiyor. `aider/agent/yapistirma.py`
uzun yapıştırmayı yer tutucuya indiriyor, gönderirken gerçek metni geri
koyuyor — modele giden şey değişmiyor.

Yer tutucu istatistik taşıyor: `[#1 yapıştırıldı: 120 satır, 5.789 karakter,
~2.894 token]`. Token tahmini dar pencerede işe yarıyor; göndermeden önce
görmek, sonradan bağlam hatası almaktan iyi.

Kısa yapıştırma olduğu gibi giriyor (eşik: 4 satır ya da 400 karakter). Yer
tutucusu bozulan metin sessizce kaybolmuyor, olduğu gibi gidiyor.

## Mod göstergesi

Mevcut izin modu prompt'un içinde durur:

```
agent ⏸ plan modu>
agent ⏵ onay modu>
agent ⏵⏵ oto mod>
```

`shift+tab` modlar arasında dolaşır, `/mod` üçünü açıklamasıyla listeler,
`/mod oto` doğrudan geçer. Glyph terminalin kodlamasında yoksa ASCII'ye
düşülür (`||`, `>`, `>>`).

**Alt bilgi çubuğu (`bottom_toolbar`) denendi ve geri alındı.** Terminali raw
modda bırakıp merdiven etkisi yapıyordu — her satır bir öncekinin bittiği
sütundan başlıyordu. Prompt öneki aider'in zaten doğru çizdiği tek yer;
oraya yazmak hem sağlam hem her zaman görünür.

Upstream'e dokunuş `io.py`'de üç nokta: `agent_status` / `agent_cycle_mode`
kancaları, prompt önekini üreten `build_prompt_prefix()` ve prompt mesajının
**sabit dizge yerine çağrılabilir** verilmesi. İlk ikisi diğer coder'larda
`None` kalır.

Üçüncüsü şart: mesaj sabit dizgeyse `shift+tab` modu değiştiriyor ama
`invalidate()` aynı metni yeniden çiziyor ve değişim ekranda ancak bir
sonraki prompt'ta görünüyor. `test_prompt_message_is_callable_and_follows_mode`
bunu koruyor.

## Coder değişiminde bırakılması gerekenler

AgentCoder iki şeyi kendi dışına bağlıyor ve ikisi de coder değişince
sızıyordu:

- `io.agent_status` / `io.agent_cycle_mode` AgentCoder'ın metotlarına
  bağlanıyor. `/ask` ile geçilince bağlı kalıyor ve prompt hâlâ
  "⏵ onay modu" yazıyordu — kullanıcı agent modunda sandığı hâlde değil.
- MCP sunucu süreçleri yalnızca `atexit` ile kapanıyor, yani her coder
  değişiminde bir takım daha açılıyordu.

`main.agent_kancalarini_birak()` ikisini de `SwitchCoder` yakalandığında
bırakıyor; AgentCoder'a dönülürse kancalar kendi `__init__`'inde geri
kuruluyor. Agent katmanına yeni bir global bağ eklersen bu fonksiyona da
eklemek gerekiyor.

## Oturum sürekliliği

Upstream'de yoktu. `--restore-chat-history` agent modunda kullanılamıyor:
markdown günlüğün tamamını okuyor ve `tool_calls` / `role="tool"` mesajlarını
kaybediyor. Agent geçmişinin yarısı araç trafiği olduğu için bu geçmişin
yarısını atmak.

`aider/agent/oturum.py` her oturumu JSONL olarak, mesajları API biçiminde
saklıyor. `--continue` son oturumu sürdürüyor, `/oturumlar` listeliyor.

Bir tuzağı var ve sessiz: bütçe kırpması `tool_calls` taşıyan assistant
mesajını kendi `tool` yanıtlarından ayırırsa endpoint isteği reddediyor.
`budala()` bu yüzden kesme noktasını ileri alıp ilk `user` mesajına
hizalıyor; `TestOturumButcesi` dört ayrı bütçede yetim `tool` mesajı
kalmadığını sınıyor.

## Çevrimdışı çalışma

Hedef ortam hava boşluklu. `--offline` ağa çıkan her davranışı tek noktadan
kapatır: sürüm denetimi, analitik, URL çekme, `/voice` ve `npx`/`uvx` ile
başlayan MCP sunucuları. Gerekçeler `AGENT.md`'de; en kritiği sürüm
denetimi — `versioncheck.check_version` içindeki `requests.get` **zaman
aşımsız**, yani ağ yokken açılış TCP zaman aşımı kadar askıda kalıyor.

Zorlamayı `main.cevrimdisi_uygula()` yapıyor; ayrı bir fonksiyon olmasının
sebebi `fork_dogrula.py`'nin bayrağın varlığını değil **etkisini**
sınayabilmesi.

Yeni bir özellik eklerken kuralı sor: ağa çıkıyor mu? Çıkıyorsa çevrimdışı
modda ne yapmalı?

## Bağlam disiplini

Agent modunda bağlamı üç şey şişiriyordu; üçü de ölçülüp kapatıldı.

**Araçlar okudukları dosyayı kalıcı bağlama eklemiyor.** `Read`/`Write`/`Edit`
eskiden dosyayı `abs_fnames`'e ekliyordu; aider o listedeki her dosyanın **tam
içeriğini her isteğe** yeniden gömdüğü için (`get_chat_files_messages`) model
birkaç dosya okuduktan sonra pencere yalnızca dosya tekrarlarıyla doluyordu.
Okunan içerik zaten araç sonucu olarak geçmişte duruyor. Kullanıcının `/add`
ile eklediği dosyalar elbette bağlamda kalır — değişen, araçların sessizce
dosya eklemesi.

**Repo haritası agent modunda varsayılan kapalı.** Modelin Glob/Grep/Read'i
var; harita her isteğe yeniden giriyor ve sohbete dosya eklenmemişken
`map_multiplier_no_files` ile sekiz katına çıkıyor. Açmak isteyen
`--map-tokens` verir.

**Bellek ve proje talimatı bütçeleri pencereye göre ölçekleniyor.** Sabit
12.000 ve 20.000 karakter, 8k pencereli bir modelde iş yapacak yer
bırakmıyordu; artık pencerenin yüzde 10'u ve 15'i, eski değerler tavan.

**Karakter/token oranı 4 değil 2.** `KARAKTER_BASINA_TOKEN` bütün bütçeleri
token'dan karaktere çeviriyor ve 4 yazıyordu — İngilizce düz metin için doğru,
bu fork'un çalıştığı içerik için değil. Ölçüldü (gpt-4o tokenizer): Türkçe
sistem promptu 2,70 kar/token, sunucu envanteri gibi yapılı metin 2,02. Yani
"pencerenin çeyreği" diye ayrılan yer gerçekte yarısını yiyordu. Sabit en kötü
ölçüme, 2.0'a çekildi; iyimser olmanın bedeli modelin ortada kalması.

**Beceri katalogu pencereye göre kısılıyor.** 37 becerinin ad + açıklama
listesi 9.838 karakter, yani 16k pencereli bir modelde HER istekte ~3.650
token — pencerenin beşte biri. Karşılığı da yok: beceri seçimi `eslestir` ile
kodda yapılıyor, model bu listeden seçmiyor. Bütçe (`KATALOG_PAYI`) yetmezse
katalog önce adlara iner, sonra tümden düşer; deterministik tetikleme üç
durumda da çalışır.

Ölçüm, 16k pencere, gpt-4o tokenizer:

| | önce | sonra |
|---|---|---|
| sistem promptu | 4.549 token | 1.186 token |
| araç şemaları | 2.257 token | 1.488 token |
| **sabit yük** | **%42** | **%16** |
| 800 satır okuduktan sonra kalan | 1.328 token | 9.564 token |

`TestKucukPencere` sabit yükün pencerenin çeyreğini aşmadığını sınıyor.

**Dar pencerede lüks araçların şeması sunulmuyor.** Araç şemaları her isteğe
giriyor: on aracın şeması 2.246 token, 16k pencerenin %14'ü. `Skill`,
`Hatirla` ve `TodoWrite` bunun 766 token'ı (%4,7) ve 4B sınıfı bir modelin
neredeyse hiç çağırmadığı araçlar. `KUCUK_PENCERE` (32k) altında sunulmuyorlar;
yetenek kaybolmuyor çünkü beceri tetikleme zaten kodda deterministik ve
`/hatirla` kullanıcıda duruyor. Açılış duyurusunda hangi araçların düştüğü
yazıyor.

**Araç şemalarının kendi bütçesi var.** Yerleşik araçlar 16k pencerede 1.488
token; MCP araçları buna ekleniyor ve ölçüldü: sekiz MCP aracı %26, yirmi dört
tanesi %60. İki MCP sunucusu ekleyen biri, model daha tek satır okumadan
pencerenin yarısını harcıyor ve sebebini göremiyordu. `SEMA_PAYI` (%20)
aşılırsa MCP araçları kesiliyor; yerleşikler asla düşmez, çünkü agent döngüsü
onlarsız çalışmaz. Düşenler bir kez, adlarıyla duyuruluyor — sessizce
kaybolmaları "model neden bu aracı çağırmadı" sorusuna yol açıyor.

**Read bütçeye göre sayfalıyor.** Eskiden 2000 satır okuyup sonucu ortadan
kırpıyordu: model dosyanın yarısını görüyor ama kalanını nereden isteyeceğini
bilmiyordu. Artık sayfa bütçeden hesaplanıyor ve başlıkta devam offset'i
**açıkça** yazıyor (`devamı için Read(offset=148)`). 800 satırlık bir envanter
16k pencerede altı sayfada okunuyor, hiçbiri pencereyi taşırmıyor.

**Bağlam toparlama kademeli — tek kademe çıkmaz sokaktı.** `_baglami_toparla`
yalnızca korunan son altı mesajın DIŞINDAKİ araç çıktılarını kısaltıyordu.
Ölçüldü: 16k pencerede sistem promptu + bir beceri gövdesi + üç `ssh` çıktısı,
o altı mesajın dışında kısaltılacak hiçbir şey bırakmıyor; döngü "kısaltacak
eski çıktı kalmadı" deyip işi yarıda bırakıyordu. Muafiyet artık kademeli
(`KORUMA_KADEMELERI = (6, 2, 0)`): önce eskiler, yetmezse kuyruğa girilir.
Son adımın çıktısını kısaltmak, işi yarıda bırakmaktan iyidir; kullanıcı
uyarıda hangisinin olduğunu görüyor. `TestBaglamCikmazi` senaryoyu birebir
kuruyor.

**Son sözü tokenizer söylüyor.** Karakter/token oranı bir tahmin ve sınıra
yakınken tutmuyor. srvsatellite'te ölçüldü: istek **16385 token**'la
reddedildi, modelin sınırı 16384 — bir token yüzünden iş yarıda kaldı.
Karakter kırpmasından sonra `_token_ile_dogrula` gerçek sayımla bakıyor ve
gerekirse en büyük araç çıktısını yarılamayı sürdürüyor. Karakter hesabı
"sığıyor" dese bile bu kontrol atlanmıyor: kötü tokenlaşan çıktıda 27.693
karakter sınırın altında ama 15.293 token tavanın üstünde. Sayım
yapılamıyorsa (özel endpoint'lerde olabiliyor) iş durdurulmuyor.

**Uzun oturumlar özetlenerek sıkıştırılıyor.** `_baglami_toparla` yalnızca
tek bir mesajın araç döngüsü içinde çalışıyordu; turlar arasında biriken
geçmişe kimse dokunmuyordu. Aider'da o işi `move_back_cur_messages` yapar
ama agent modunda o çağrı yalnızca **dosya düzenlendiğinde** yürüyor —
teşhis oturumlarının çoğu hiçbir dosyaya dokunmuyor, dolayısıyla geçmiş
sınırsız büyüyordu.

`aider/agent/sikistirma.py` geçmişi modele özetletip yerine koyuyor. Son iki
kullanıcı turu aynen kalıyor. `/ozet` elle çalıştırır (`/ozet 4` dört tur
korur), pencere dolmaya yaklaşınca kendiliğinden de tetiklenir;
`--no-auto-compact` bunu kapatır.

Veri kaybı yok: özet yalnızca modele giden bağlamı değiştirir, oturumun tam
kaydı `.aider/sessions/` altındaki JSONL'de durmaya devam eder.

Özetleme, ayrı bir zayıf model tanımlıysa (`--weak-model`) oraya gidiyor:
özet çıkarmak metin sıkıştırma işi, asıl modelin muhakemesine ihtiyacı yok.
Dökümün bütçesi de **özetleyen** modelin penceresinden hesaplanıyor. Sabit
60.000 karakterlik tavan 16k pencereli bir modelde 20.800 token'lık istek
üretiyordu — `/ozet` tam da kurtarmaya çalıştığı modelde patlıyordu.

İki tuzağı var, ikisi de sınanıyor. Kesme noktası her zaman bir `user`
mesajına hizalanıyor — ortada kalan bir `tool_calls` endpoint tarafından
reddediliyor (`oturum.budala` ile aynı sebep). Özet mesajı `assistant`
rolünde giriyor: hemen ardından korunan blok `user` ile başlıyor ve arka
arkaya iki `user` mesajı vLLM/Qwen sohbet şablonlarını bozuyor. Bir de arka
arkaya sıkıştırmalarda önceki özet döküme her zaman tam giriyor, yoksa en
eski bilgi tur tur eriyor.

## Beceri tetikleme deterministik

Modelin `Skill` aracını kendiliğinden çağırmasını beklemek 4B sınıfında
çalışmıyor — ölçüldü, gemma4:e4b 14 beceri yüklüyken aracı bir kez bile
çağırmadı. Eşleştirme artık kodda: isteğin metni tetikleyici ifadelerle
karşılaştırılıyor, en isabetli tek beceri o turun mesajına iliştiriliyor.

Tetikleyiciler `description`'daki tırnak içi ifadelerden okunuyor; 37
becerinin hepsi zaten öyle yazılmıştı, yani hiçbir beceri dosyası
düzenlenmeden çalıştı.

Gövde kalıcı geçmişe DEĞİL, yalnızca o turun mesaj listesine giriyor; yoksa
her turda birikip bağlamı beceri metinleriyle doldurur. Ayrı bir mesaj değil,
son kullanıcı mesajının sonuna iliştiriliyor: arka arkaya iki `user` mesajı
bazı sohbet şablonlarını (vLLM/Qwen) bozuyor.

Tetikleyici ayarlamak deneme gerektiriyor; `/skills tetik <istek>` modeli
çalıştırmadan sıralamayı gösteriyor.

## Zayıf model dayanıklılığı

4B sınıfı modeller araç sonucundan sonra **boş yanıt** vermeye eğilimli.
Döngü eskiden ilk boşlukta pes edip işi yarıda bırakıyordu; artık bir kez
dürtüyor (`MAX_BOS_DURTME = 1`) ve boş assistant mesajını geçmişe koymuyor.
İki kez dürtmek boş-dürtme-boş döngüsü yarattığı için sınır bir.

## Bellek ve proje talimatları

Upstream aider'da ikisi de yoktu; agent katmanı ekledi.

**Proje talimatları** — depo kökündeki `AGENTS.md`, `KURALLAR.md`, `CLAUDE.md`
ya da `CONVENTIONS.md` her oturumda sistem promptuna eklenir. Genel yönergeleri
ezer.

**Bellek** — `aider/agent/memory.py`. Kısa notlar, her biri tek dosya. Üç
dizinden okunur (beceri sistemiyle aynı desen):

| Dizin | Kapsam | Depoya girer |
|---|---|---|
| `.aider/memory/` | proje, kişisel | hayır |
| `aider-memory/` | proje, paylaşılan | evet |
| `~/.aider/memory/` | tüm projeler, kişisel | hayır |

Komutlar: `/hatirla <başlık> :: <not>`, `/bellek`, `/unut <başlık>`.
Model de `Hatirla` aracıyla kendisi not alabilir; yan etkili sayıldığı için
onay ister ve plan modunda sunulmaz.

Notların tamamı sistem promptuna girer (12k karakter bütçesiyle). Bütçe
aşılırsa en yeniler tutulur ve duyuruda kaç notun düştüğü yazar.

## Yazma disiplini

Test başarısız olduysa çıktısıyla söyle. Bir adımı atladıysan atladığını söyle.
Doğrulamadığın bir şeyi "çalışıyor" diye raporlama — bu depoda bir aracın
"çalıştığını" iddia etmenin ölçüsü onu çalıştırmış olmaktır.
