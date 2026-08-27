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
  permissions.py  Kural tabanlı izin sistemi
  mcp.py          MCP istemcisi (stdio, JSON-RPC 2.0)
  skills.py       SKILL.md keşfi ve kademeli açılım
  todo.py         Görev listesi
  plan.py         Plan modu
  model_setup.py  /model-ekle akışı

aider/coders/
  agent_coder.py     Araç döngüsü
  agent_prompts.py   Sistem promptu
```

### Upstream'e dokunulan beş nokta

Çakışma yüzeyi bilinçli olarak buraya sınırlandı. Bir upstream dosyasını
değiştirmek zorunda kalırsan yamayı en küçük blokta tut ve nedenini yorumda yaz.

| Dosya | Ne yapıldı |
|---|---|
| `aider/models.py` | `send_completion` çok araçlı `tool_choice="auto"` destekliyor |
| `aider/coders/__init__.py` | `AgentCoder` kaydı |
| `aider/args.py` | `--agent`, `--plan`, `--auto`, `--permission-mode`, `--max-tool-iterations` |
| `aider/main.py` | Agent kwarg'larının yalnızca agent coder'a geçirilmesi |
| `.gitignore` | `.env` ve `.mcp.json` ignore |

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

Bu betik fork'un beş dokunuş noktasının hâlâ **çalıştığını** doğrular — dosyada
metin aramaz, kodu gerçekten çağırır. Bir merge yaman satırları koruyup
davranışı bozabilir; metin araması bunu kaçırır.

Tüm yordamı otomatik yürüten sarmalayıcı:

```bash
./scripts/upstream_birlestir.sh              # en son upstream main
./scripts/upstream_birlestir.sh v0.90.0      # belirli bir etiket
```

Ayrıntılı yordam ve çakışma çözme rehberi: `aider-skills/upstream-birlestir/SKILL.md`
(agent modunda `/skills` ile de erişilir).

## Beceriler

`aider-skills/` altında sekiz beceri var. Agent modunda model bunları
kendiliğinden yükler; sen de referans olarak okuyabilirsin.

| Beceri | Ne zaman |
|---|---|
| `kod-inceleme` | Değişiklik gözden geçirme |
| `guvenlik-incelemesi` | Güvenlik açığı arama |
| `sadelestir` | Tekrar ayıklama, ölü kod temizliği |
| `hata-ayikla` | Hata ve çöken test araştırması |
| `test-yaz` | Test yazma |
| `beceri-yaz` | Yeni beceri yazma |
| `mcp-ekle` | MCP sunucusu ekleme ve teşhis |
| `upstream-birlestir` | Upstream'den güncelleme |

Yeni beceri: `/skills new <ad>` — iskeleti `aider-skills/` altına yazar.

## Yazma disiplini

Test başarısız olduysa çıktısıyla söyle. Bir adımı atladıysan atladığını söyle.
Doğrulamadığın bir şeyi "çalışıyor" diye raporlama — bu depoda bir aracın
"çalıştığını" iddia etmenin ölçüsü onu çalıştırmış olmaktır.
