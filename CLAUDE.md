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
  ssh_tool.py     Ssh — sunucu adını ~/.ssh/config'e karşı doğrular
  permissions.py  Üç katmanlı izin sistemi (deny / ask / allow)
  mcp.py          MCP istemcisi (stdio, JSON-RPC 2.0)
  skills.py       SKILL.md keşfi ve kademeli açılım
  todo.py         Görev listesi
  plan.py         Plan modu
  model_setup.py  /model-ekle akışı

aider/coders/
  agent_coder.py     Araç döngüsü
  agent_prompts.py   Sistem promptu
```

### Upstream'e dokunulan sekiz nokta

Çakışma yüzeyi bilinçli olarak buraya sınırlandı. Bir upstream dosyasını
değiştirmek zorunda kalırsan yamayı en küçük blokta tut ve nedenini yorumda yaz.

| Dosya | Ne yapıldı |
|---|---|
| `aider/models.py` | `send_completion` çok araçlı `tool_choice="auto"` destekliyor |
| `aider/coders/__init__.py` | `AgentCoder` kaydı |
| `aider/args.py` | `--agent`, `--plan`, `--auto`, `--permission-mode`, `--max-tool-iterations` |
| `aider/main.py` | Agent kwarg'larının yalnızca agent coder'a geçirilmesi |
| `aider/io.py` | Mod göstergesi kancaları ve `shift+tab` |
| `aider/commands.py` | On bir slash komutu |
| `.gitignore` | `.env` ve `.mcp.json` ignore |
| `README.md` | Fork'un kendi ön yüzü; upstream'inki `ORIJINAL-README.md` |

En kritik olanı `models.py`: upstream `tool_choice`'u **tek bir fonksiyona
zorluyordu**, bu da agentic döngüyü imkânsız kılıyor.

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
- `aider-skills/` — paylaşılan beceriler

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

## Beceriler

`aider-skills/` altında 37 beceri var. Agent modunda model bunları
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

## Ses girişi

`/voice` upstream'den geliyor, fork dokunmadı. İki tuzağı var ve ikisi de
sessiz: `aider/voice.py` model adını `whisper-1` olarak sabit yazıyor ve
`litellm.transcription`'a `api_base` geçirmiyor — parametre kabul ediliyor
ama verilmiyor. Dolayısıyla `OPENAI_API_BASE` boşsa **ses kaydı
`api.openai.com`'a gider**. Ayrıntı ve kontrol yordamı `AGENT.md`'de.

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
