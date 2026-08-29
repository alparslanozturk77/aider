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

## Araçlar

| Araç | Ne yapar | Onay ister |
|---|---|---|
| `Read` | Dosyayı satır numaralı okur; `offset`/`limit` ile parça parça | hayır |
| `Write` | Dosyayı tamamen yazar, üstüne yazar | **evet** |
| `Edit` | Birebir string değişimi; belirsiz eşleşmede hata verir | **evet** |
| `Bash` | Kabuk komutu çalıştırır, zaman aşımlı | **evet** |
| `Glob` | Desene uyan dosyaları bulur, tarihe göre sıralı | hayır |
| `Grep` | İçerikte regex arar; ripgrep varsa onu kullanır | hayır |
| `TodoWrite` | Çok adımlı işlerde görev listesi tutar | hayır |
| `Skill` | Bir beceriyi bağlama yükler | hayır |
| `ExitPlanMode` | Planı onaya sunar (yalnızca plan modunda) | **evet** |

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

Aynı isim birden fazla yerde varsa **ilk kök kazanır**. Sıra bilinçli: paylaşılan
bir beceriyi lokalde geçici olarak ezebilirsin.

Yeni beceri oluşturmak için `/skills new <ad>` — iskeleti `aider-skills/`
altına, yani depoya girebilen konuma yazar. `/skills` ile diskten yeniden
yükleyip aider'ı kapatmadan test edersin.

Depodaki `aider-skills/kod-inceleme` ve `aider-skills/test-yaz` çalışan
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
```

`allow` listesindeki çağrılar sorulmadan çalışır, `deny` listesindekiler
sorulmadan engellenir. Reddetme her zaman izni yener — `auto` modda bile.

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

Kaldırılamayan yerleşik bir reddetme listesi de var: `rm -rf /`, `sudo`,
`mkfs*`, `dd if=*`, `git push`, `git reset --hard`, ve kabuğa boru
(`curl ... | sh` kalıbı). Bunlar `auto` modda da engellenir.

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
| `/mcp` | MCP sunucularını ve araçlarını listeler |
| `/mcp reload` | MCP sunucularını yeniden başlatır |
| `/permissions` | İzin modunu ve kurallarını gösterir |
| `/todo` | Mevcut görev listesini gösterir |
| `/model <ad>` | Modeli değiştirir (aider'ın kendi komutu) |
| `/model-ekle` | Yeni modeli adım adım tanımlar ve kaydeder |

`/skills` beceriyi yeniden okuduğu için, `SKILL.md` dosyasını düzenleyip aider'ı
yeniden başlatmadan test edebilirsin.

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
- **Beceriler** — depodaki 30 becerinin yüklenebildiği ve tetikleme
  açıklamalarının var olduğu

Ayrıca `scripts/fork_dogrula.py` fork değişmezlerini davranışsal olarak sınar.

Tüm upstream test takımı da geçmeye devam eder (toplam 602 test).
