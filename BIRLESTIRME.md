# Upstream'den güncelleme

Bu depo [Aider-AI/aider](https://github.com/Aider-AI/aider)'ın forkudur.
Fork noktası: `5dc9490`.

Bu belge, aylar sonra okuyacak kişi için yazıldı — o kişi sen olsan bile.
Ayrıntıları hatırlamayacaksın.

---

## Hızlı yol

```bash
cd ~/projects/aider
git status                                    # temiz olmalı
./scripts/upstream_birlestir.sh               # en son upstream main
./scripts/upstream_birlestir.sh v0.92.0       # belirli bir sürüm
```

Betik sırayla: upstream'i getirir → dokunduğumuz dosyalarda ne değiştiğini
gösterir → merge eder → **fork değişmezlerini doğrular** → testleri çalıştırır.

Çakışma çıkarsa durur ve kararı sana bırakır. Çözdükten sonra:

```bash
git add <dosyalar> && git commit
.venv/bin/python scripts/fork_dogrula.py
.venv/bin/python -m pytest tests/basic -q
```

Her şey yeşilse:

```bash
git push fork claude-code-layer
```

Vazgeçmek: `git merge --abort` (merge sırasında) ya da
`git reset --hard <merge-öncesi-hash>` (merge sonrası).

---

## Merge'in asıl riski

Çakışma değil — çakışma görünür, git sana söyler.

Asıl risk, merge'in **yama satırlarını koruyup davranışı bozması**. Upstream
`send_completion`'ı yeniden yazarsa bizim satırlarımız dosyada kalabilir ama
etkisiz olur. Hiçbir çakışma görmezsin, testler geçebilir, ama agent modu
sessizce çalışmaz.

Bu yüzden `scripts/fork_dogrula.py` metin aramaz, **kodu çağırır**. On iki
değişmezi davranışsal olarak sınar — yedi dokunuş noktasının hepsini ve agent
katmanının kendi bütünlüğünü.

```bash
.venv/bin/python scripts/fork_dogrula.py --liste   # ne kontrol ediyor
```

---

## Upstream'de neye bakmalı

Merge öncesi:

```bash
git fetch upstream
git log --oneline HEAD..upstream/main | head -40
git diff HEAD...upstream/main --stat -- aider/models.py aider/io.py \
    aider/args.py aider/main.py aider/coders/__init__.py aider/commands.py
git diff HEAD...upstream/main -- HISTORY.md | head -60
```

Alarm veren değişiklikler:

| Upstream'de değişirse | Ne kırılabilir |
|---|---|
| `models.py` içinde `send_completion` | **En kritik.** Agent döngüsü tamamen durur |
| `io.py` içinde `get_input` ya da tuş bağlamaları | Mod göstergesi, shift+tab |
| `commands.py` içinde `Commands` sınıfının yapısı | Bizim 10 komutumuz |
| `base_coder.py` içinde `send_message` / `format_messages` | AgentCoder bunları override ediyor |
| `coders/__init__.py` içindeki `__all__` biçimi | AgentCoder kaydı |
| litellm sürümü | Tool calling davranışı değişebilir |

`base_coder.py`'ye **dokunmuyoruz** ama `AgentCoder` ondan türüyor ve
`send_message` ile `format_messages`'ı override ediyor. Upstream bu metotların
imzasını değiştirirse çakışma çıkmaz ama agent bozulur — `fork_dogrula.py`
yakalar.

---

## Sekiz dokunuş noktası

Çakışma yüzeyi bilinçli olarak bu yedi noktayla sınırlı. Bir merge birini
silerse aşağıdan elle geri koyabilirsin.

### 1. `aider/models.py` — `send_completion`

**En kritik olan.** Upstream `tool_choice`'u tek bir fonksiyona zorluyor; bu
agentic döngüyü imkânsız kılıyor çünkü model araçlar arasından kendisi
seçebilmeli.

`if functions is not None:` bloğunun içi şöyle olmalı:

```python
        if functions is not None:
            # İki biçim destekleniyor:
            #  1) Eski aider biçimi: çıplak function şemaları listesi.
            #  2) Agentic biçim: önceden {"type": "function", ...} sarmalanmış.
            already_wrapped = all(
                isinstance(f, dict) and f.get("type") == "function" for f in functions
            )
            if already_wrapped:
                kwargs["tools"] = list(functions)
                kwargs["tool_choice"] = "auto"
            else:
                function = functions[0]
                kwargs["tools"] = [dict(type="function", function=function)]
                kwargs["tool_choice"] = {
                    "type": "function",
                    "function": {"name": function["name"]},
                }
```

Upstream'in tek-fonksiyon davranışı `else` dalında **aynen korunmalı**;
`wholefile_func` gibi coder'lar ona bağlı.

**Doğrulama:** `fork_dogrula.py` içindeki `tool_choice=auto` ve
`eski tool biçimi korunuyor` kontrolleri.

### 2. `aider/coders/__init__.py` — kayıt

```python
from .agent_coder import AgentCoder      # ilk satır
...
__all__ = [
    AgentCoder,                          # listenin başında
    HelpCoder,
    ...
]
```

`Coder.create(edit_format="agent")` bu kayıt üzerinden çözülür. Kayıt yoksa
belirti: `Unknown edit format agent`.

### 3. `aider/args.py` — bayraklar

`--architect` tanımının hemen ardına beş bayrak: `--agent`, `--plan`,
`--max-tool-iterations`, `--permission-mode`, `--auto`.

`--agent` ve `--auto` `store_const` ile sırasıyla `edit_format` ve
`permission_mode` ayarlar.

### 4. `aider/main.py` — agent kwarg'ları

`Coder.create` çağrısından önce:

```python
    agent_kwargs = {}
    if args.edit_format == "agent":
        agent_kwargs = dict(
            plan_mode=args.plan,
            max_iterations=args.max_tool_iterations,
            permission_mode=args.permission_mode,
        )
```

ve `Coder.create(...)` çağrısının son argümanı olarak `**agent_kwargs,`.

Koşul şart: diğer coder'lar bu anahtar kelimeleri kabul etmez, koşulsuz
geçirirsen `--edit-format diff` çöker.

### 5. `aider/io.py` — üç küçük ekleme

`__init__` içinde iki opsiyonel kanca:

```python
        self.agent_status = None       # callable -> mod göstergesi metni
        self.agent_cycle_mode = None   # callable -> shift+tab
```

`get_input` içinde prompt önekine:

```python
        if self.agent_status:
            try:
                prompt_prefix += " " + self.agent_status()
            except Exception:
                pass
```

ve tuş bağlaması:

```python
        @kb.add("s-tab")
        def _(event):
            if self.agent_cycle_mode:
                self.agent_cycle_mode()
                event.app.invalidate()
```

İkisi de diğer coder'larda `None` kalır, davranış değişmez.

> **Denenip geri alındı:** `bottom_toolbar=self.agent_status`. Terminali raw
> modda bırakıp merdiven etkisi yapıyordu — her satır bir öncekinin bittiği
> sütundan başlıyordu, açılış duyuruları dahil. Tekrar deneme.

### 6. `aider/commands.py` — on komut

`/agent`, `/plan`, `/skills`, `/mcp`, `/permissions`, `/todo`, `/mod`,
`/hatirla`, `/bellek`, `/unut`, `/model-ekle` ve yardımcı `_require_agent`,
`_new_skill`.

Hepsi `Commands` sınıfına eklenen bağımsız metotlar; upstream metotlarını
değiştirmiyorlar. Çakışma olursa metotları olduğu gibi yeni yere taşı.

### 7. `.gitignore` — iki satır

```
.env
.mcp.json
```

**Negasyon (`!`) kullanma.** Aider'ın `--add-gitignore-files` özelliği dosya
sonuna kendi `.aider*` satırını ekliyor ve son eşleşen kural kazandığı için
negasyonlar sessizce ölüyor. Bu oturumda üç kez oldu.

Bu yüzden depoya girmesi gereken hiçbir şey `.aider` ile başlayan dizinde
durmuyor: şablonlar `ornek/`, beceriler `aider-skills/`.

---

## README çakışması

`README.md` upstream'de sık değişir ve fork onu tamamen değiştirdi; upstream'in
kendi metni `ORIJINAL-README.md`'de duruyor. Merge'de neredeyse her seferinde
çakışır ve çözümü **her zaman aynı**:

```bash
git checkout --ours README.md          # fork'un ön yüzü kalsın
git show MERGE_HEAD:README.md > ORIJINAL-README.md   # upstream'inki güncellensin
git add README.md ORIJINAL-README.md
```

`scripts/fork_dogrula.py` içindeki "README fork'un" kontrolü bu adımın
atlandığını yakalar: merge upstream README'sini geri getirdiyse GitHub'da
fork'un değil aider'ın kendi sayfası görünür.

## Değişmez bozulursa

`fork_dogrula.py` her bozuk kontrol için hangi dosyaya bakman gerektiğini ve o
dokunuşun **neden** orada olduğunu yazar.

```bash
git diff <merge-öncesi-hash>..HEAD -- aider/models.py
```

ile merge'in o dosyada ne yaptığını gör, yukarıdaki bölümden yamayı geri koy,
sonra tekrar doğrula.

Bir kontrolü "geçsin diye" gevşetme. Kontrol bir davranışı sınıyor; gevşetmek
davranışı geri getirmez, yalnızca kaybını gizler.

---

## Yeni özellik eklerken

Sıralama önemli — çakışma yüzeyini büyütmemek için:

1. Önce `aider/agent/` içinde yeni bir **araç** ya da modül olarak dene
2. Olmuyorsa `aider/coders/agent_coder.py` içinde
3. Upstream dosyasına dokunmak **son çare**

Upstream dosyasına dokunmak zorunda kaldığında:

- Yamayı mümkün olan en küçük blokta tut
- Neden orada olduğunu yorumda yaz — bir sonraki merge'de sen ya da başkası
  onu silmeye kalkacak
- `scripts/fork_dogrula.py` içine o davranışı sınayan bir kontrol ekle
- Kontrolü kasten bozarak gerçekten yakaladığını doğrula. Yakalamayan kontrol
  tiyatrodur.
- Bu belgeye dokunuş noktası olarak ekle

---

## Sürüm yükseltme sonrası el kontrolü

Testler ve değişmezler yeşil olsa bile, gerçek bir modelle bir tur at:

```bash
cd ~/ops && ~/projects/aider/.venv/bin/aider
```

- Açılış duyurusunda araç ve beceri sayıları doğru mu
- `shift+tab` modu değiştiriyor mu, prompt güncelleniyor mu
- Basit bir görev: `hostname çalıştır` → araç çağrılıyor ve **çıktı görünüyor** mu
- `/mod`, `/skills`, `/bellek` çalışıyor mu

Endpoint değiştiyse önce yetenek testi:

```bash
./ornek/arac-testi.sh <model> <api-base> <anahtar>
```

İki aşamayı ayrı ölçer: araç çağırabiliyor mu, ve araç **sonucunu** görebiliyor
mu. İkincisi kalırsa model sonsuz döngüye girer ve bu yalnızca round-trip
sınanarak görülür.

---

## Hızlı referans

```bash
# durum
git log --oneline -5
.venv/bin/python scripts/fork_dogrula.py

# birleştirme
./scripts/upstream_birlestir.sh

# doğrulama
.venv/bin/python -m pytest tests/basic -q
.venv/bin/python -m flake8 aider/ tests/basic/test_agent.py

# geri alma
git merge --abort
git reset --hard <hash>

# gönderme
git push fork claude-code-layer
```
