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

```bash
git clone <bu-fork-un-adresi> aider
cd aider
python3.12 -m venv .venv
.venv/bin/pip install -e .
```

Kurum endpoint'ini tanımla:

```bash
cp .env.ornek .env                                    # endpoint + anahtar
cp .aider.conf.yml.ornek .aider.conf.yml              # model + agent ayarları
cp .aider.model.metadata.json.ornek .aider.model.metadata.json  # bağlam penceresi
```

`.env` içindeki `OPENAI_API_BASE` ve `OPENAI_API_KEY` değerlerini kurumun
verdiği değerlerle doldur. Model adını doğrulamak için:

```bash
curl -s "$OPENAI_API_BASE/models" \
  -H "Authorization: Bearer $OPENAI_API_KEY" | jq -r '.data[].id'
```

Çıkan kimliği `.aider.conf.yml` içinde `openai/` önekiyle yaz:
`model: openai/qwen3-coder`

Çalıştır:

```bash
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

Onay isteyen araçlar `--yes-always` ile otomatik onaylanır. Kurumsal ortamda
bunu açmadan önce iki kez düşün: model onaysız komut çalıştırabilir hale gelir.

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

1. `<proje>/.aider/skills/` — projeye özgü, depoya girer, takımla paylaşılır
2. `~/.aider/skills/` — kişisel, tüm projelerde geçerli
3. `AIDER_SKILLS_PATH` içindeki dizinler — kurum geneli ortak beceriler

Aynı isim birden fazla yerde varsa **ilk kök kazanır**: proje becerisi kişisel
beceriyi ezer.

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
| `/todo` | Mevcut görev listesini gösterir |

`/skills` beceriyi yeniden okuduğu için, `SKILL.md` dosyasını düzenleyip aider'ı
yeniden başlatmadan test edebilirsin.

## Bayraklar

| Bayrak | Varsayılan | Ne yapar |
|---|---|---|
| `--agent` | — | Agent moduna geçer (`--edit-format agent` ile aynı) |
| `--plan` | `false` | Plan modunda başlar |
| `--max-tool-iterations N` | `50` | Tek mesajda izin verilen azami model turu |

`--max-tool-iterations` bir emniyet sübabıdır: model araç döngüsünde takılıp
kalırsa sınıra ulaşıldığında durur ve uyarı basar.

## Mimari

```
aider/agent/
  registry.py   ToolRegistry + ToolContext + ToolError
  tools.py      Read, Write, Edit, Bash, Glob, Grep
  skills.py     SKILL.md keşfi, frontmatter ayrıştırma, Skill aracı
  todo.py       Görev listesi + TodoWrite aracı
  plan.py       Plan modu + ExitPlanMode aracı

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
- `commands.py` — `/agent`, `/plan`, `/skills`, `/todo`

Bu ayrım kasıtlıdır: upstream aider'dan `git merge` yaptığında çakışma yüzeyi
beş küçük noktayla sınırlı kalır.

### Araç hataları neden istisna değil?

`ToolRegistry.run` hiçbir zaman istisna sızdırmaz; her hatayı modele geri
verilebilir bir metne çevirir. Model yanlış argüman gönderdiğinde ya da olmayan
bir dosyayı okumaya çalıştığında oturum çökmez — model hatayı görür ve kendini
düzeltir. Bu, agentic döngünün dayanıklılığının temelidir.

## Testler

```bash
.venv/bin/python -m pytest tests/basic/test_agent.py -q
```

54 test: her aracın mutlu yolu ve hata yolları, beceri keşfi ve öncelik sırası,
görev listesi doğrulaması, plan modu kısıtları, ve sahte bir modelle uçtan uca
sürülen araç döngüsü (çoklu araç çağrısı, bozuk JSON, bilinmeyen araç, döngü
sınırı).

Tüm upstream test takımı da geçmeye devam eder (529 test).
