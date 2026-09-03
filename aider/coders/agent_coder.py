"""Gerçek tool-calling döngüsüyle çalışan agentic coder.

Aider'ın klasik akışı tek atımlıdır: bağlamın tamamını gönder, yanıttaki edit
bloklarını uygula, dur. AgentCoder bunun yerine Claude Code'daki gibi bir döngü
kurar: model araç çağırır, sonucu görür, tekrar karar verir; iş bitene kadar.
"""

import json

from aider.agent.plan import PLAN_MODE_REMINDER, ExitPlanModeTool
from aider.agent.mcp import MCPManager
from aider.agent.memory import (
    INSTRUCTION_BUDGET,
    INSTRUCTION_WARN_CHARS,
    MEMORY_BUDGET,
    HatirlaTool,
    MemoryStore,
    default_memory_roots,
    load_instructions,
)
from aider.agent.oturum import DEVAM_BUTCESI, SessionStore
from aider.agent.permissions import MODE_ASK, MODE_AUTO, MODE_PLAN, load_permissions
from aider.agent.registry import ToolContext, ToolRegistry
from aider.agent import sikistirma
from aider.agent.glyph import guvenli
from aider.agent.skills import SkillLibrary, SkillTool, default_skill_roots
from aider.agent.ssh_tool import SshTool
from aider.agent.todo import TodoList, TodoWriteTool
from aider.agent.tools import (
    KARAKTER_BASINA_TOKEN,
    BashTool,
    EditTool,
    GlobTool,
    GrepTool,
    ReadTool,
    WriteTool,
)
from aider.exceptions import LiteLLMExceptions

from .agent_prompts import AgentPrompts
from .base_coder import Coder

# Tek bir kullanıcı mesajı için izin verilen azami model turu. Modelin araç
# döngüsünde sonsuza dek dönmesini engeller.
DEFAULT_MAX_ITERATIONS = 50

# Araç çıktısından kullanıcıya gösterilecek azami satır. Model zayıf olup
# sonucu özetlemese bile kullanıcı ham veriyi görsün diye var — ama ekranı
# doldurmadan: modele giden tam çıktı zaten geçmişte duruyor, buradaki
# yalnızca "ne oldu" hissi.
RESULT_PREVIEW_LINES = 8

# Kendi çıktısını zaten basan araçlar; iki kez gösterilmesinler.
KENDI_BASAN_ARACLAR = ("TodoWrite", "ExitPlanMode", "Skill")

# İlk satırı zaten özet olan araçlar. Read'in ilk satırı
# "dosya.py (satır 1-40, toplam 120)" — dosya içeriğini ekrana dökmenin
# bilgi değeri yok, model tamamını görüyor.
OZET_SATIRI_YETER = ("Read",)

# Model araç sonucundan sonra boş dönerse kaç kez dürtülecek. Bir kez
# yeterli: zayıf modeller çoğu zaman ikinci denemede devam ediyor, daha
# fazlası boş-dürtme-boş döngüsüne çeviriyor.
MAX_BOS_DURTME = 1

# Sistem promptundaki bellek ve proje talimatı bloklarının bağlam
# penceresinden alabileceği pay. Sabit karakter sınırları küçük modellerde
# promptun tamamına yakınını yiyordu: 12.000 karakter ~3.000 token, yani 8k
# pencereli bir modelde iş yapacak yer kalmıyor.
BELLEK_PAYI = 0.10
TALIMAT_PAYI = 0.15

# Otomatik yüklenen becerinin gövdesi için pay ve tavan. Tek beceri
# yükleniyor; ikisi birden bağlamın yarısını yiyor ve model asıl isteği
# kaybediyor.
BECERI_PAYI = 0.25
BECERI_TAVANI = 8_000

# Bu pencerenin altında lüks araçların şeması sunulmuyor. Şemalar her
# istekte gidiyor ve ölçüldü: on aracın şeması 2.246 token, 16k pencerenin
# %14'ü. Aşağıdaki üçü 766 token (%4,7) ve 4B sınıfı bir modelin neredeyse
# hiç çağırmadığı araçlar — Skill'i hiç çağırmadığı zaten ölçülmüştü.
# Yetenek kaybolmuyor: beceri tetikleme kodda deterministik yapılıyor,
# /hatirla kullanıcıda duruyor.
KUCUK_PENCERE = 32_000

# Araç şemalarının pencereden alabileceği azami pay. Ölçüldü: yerleşik yedi
# araç 16k pencerede 1.488 token (%9), ama MCP araçları buna ekleniyor —
# sekiz MCP aracı %26, yirmi dört tanesi %60. Yani iki MCP sunucusu ekleyen
# biri, model daha tek satır okumadan pencerenin yarısını harcıyor ve sebebini
# göremiyor. Yerleşik araçlar her zaman kalır; sığmayan MCP araçları düşer.
SEMA_PAYI = 0.20
KUCUK_PENCEREDE_KAPALI = ("Skill", "Hatirla", "TodoWrite")

# Beceri katalogunun (37 satırlık ad + açıklama listesi) alabileceği pay.
# Ölçüldü: tam katalog 9.838 karakter, 16k pencerede her istekte ~3.650
# token. Karşılığı yok — beceri seçimi kodda yapılıyor, model bu listeden
# seçmiyor. Bütçe yetmezse katalog önce adlara iner, sonra tümden düşer.
# Özetlenecek dökümün, ÖZETLEYEN modelin penceresinden alabileceği pay.
# Sabit 60.000 karakterlik tavan 16k pencereli bir modelde 20.800 token'lık
# bir istek üretiyordu: /ozet tam da kurtarmaya çalıştığı modelde patlıyordu.
# Kalan pay isteme ve üretilecek özete gidiyor.
DOKUM_PAYI = 0.6

KATALOG_PAYI = 0.05
KATALOG_TAVANI = 12_000

# Geri yüklenen önceki oturumun bağlam penceresinden alabileceği pay.
# Geçmiş, iş yapacak yerin tamamını yiyemez.
DEVAM_PAYI = 0.30

# Araç döngüsü içinde bağlamın bu oranı dolduğunda eski araç çıktıları
# kısaltılır. check_tokens yalnızca döngüden ÖNCE bakıyordu; oysa bağlamı
# şişiren şey döngünün kendisi: on tur "rpm -qa" çıktısı pencereyi bitiriyor
# ve model ortada sert bir API hatasıyla düşüyor.
DOLULUK_ESIGI = 0.85

# Kısaltmadan muaf tutulan son mesaj sayısı. Model en azından son birkaç
# adımın sonucunu ham görmeli, yoksa ne yaptığını unutuyor.
KORUNAN_SON_MESAJ = 6

# Muafiyet KADEMELİ. Tek kademe çıkmaz sokak yapıyordu: 16k pencerede sistem
# promptu + bir beceri gövdesi + üç ssh çıktısı, korunan altı mesajın DIŞINDA
# kısaltılacak hiçbir araç çıktısı bırakmıyor. Döngü "kısaltacak eski çıktı
# kalmadı" deyip işi yarıda bırakıyordu — ölçüldü, senaryo uydurma değil.
# Yer açmak için son çıktılara girmek, işi yarıda bırakmaktan iyidir.
KORUMA_KADEMELERI = (KORUNAN_SON_MESAJ, 2, 0)

# Bundan kısa araç sonuçlarını kısaltmanın kazancı yok.
KISALTMA_ESIGI = 400

# Karakter hesabı ucuz ama sınıra yakınken yanılıyor. srvsatellite'te ölçüldü:
# istek 16385 token'la reddedildi, modelin sınırı 16384 — bir token yüzünden iş
# yarıda kaldı. Karakter kırpmasından sonra son sözü tokenizer söylüyor.
TOKEN_KIRPMA_DENEMESI = 12
TOKEN_KIRPMA_TABANI = 200


class AgentCoder(Coder):
    """Claude Code tarzı araç döngüsü."""

    edit_format = "agent"
    gpt_prompts = AgentPrompts()

    def __init__(self, *args, **kwargs):
        self.plan_mode = kwargs.pop("plan_mode", False)
        self.max_iterations = kwargs.pop("max_iterations", DEFAULT_MAX_ITERATIONS)
        self.offline = kwargs.pop("offline", False)
        self.otomatik_beceri = kwargs.pop("auto_skills", True)
        self.otomatik_ozet = kwargs.pop("auto_compact", True)
        devam = kwargs.pop("devam", False)
        permission_mode = kwargs.pop("permission_mode", None) or (
            MODE_PLAN if self.plan_mode else MODE_ASK
        )
        super().__init__(*args, **kwargs)

        if permission_mode == MODE_PLAN:
            self.plan_mode = True

        builtin_tools = [
            ReadTool(),
            WriteTool(),
            EditTool(),
            BashTool(),
            SshTool(),
            GlobTool(),
            GrepTool(),
            TodoWriteTool(),
            SkillTool(),
            HatirlaTool(),
            ExitPlanModeTool(),
        ]

        # MCP sunucuları oturum başında başlatılır. Bir sunucunun ayağa
        # kalkmaması oturumu düşürmez; hata bildirilir ve devam edilir.
        self.mcp = MCPManager(self.io, self.root, offline=self.offline)
        mcp_tools = self.mcp.load()
        for err in self.mcp.errors:
            self.io.tool_error(f"MCP: {err}")

        self._builtin_tools = builtin_tools
        self.registry = ToolRegistry(builtin_tools + mcp_tools)

        # Şema maliyetleri oturum boyunca sabit; her döngü turunda yeniden
        # saymak gereksiz.
        self._sema_onbellegi = {}
        self._sema_uyarisi_verildi = False

        self.ctx = ToolContext(self)
        self.ctx.todos = TodoList()
        self.ctx.skills = SkillLibrary(default_skill_roots(self.root))
        self.ctx.memory = MemoryStore(default_memory_roots(self.root))
        self.ctx.plan_mode = self.plan_mode

        self.beceri_butcesi = self._prompt_butcesi(BECERI_PAYI, BECERI_TAVANI)
        self.katalog_butcesi = self._prompt_butcesi(KATALOG_PAYI, KATALOG_TAVANI)
        self.bellek_butcesi = self._prompt_butcesi(BELLEK_PAYI, MEMORY_BUDGET)
        self.talimat_butcesi = self._prompt_butcesi(TALIMAT_PAYI, INSTRUCTION_BUDGET)
        self.instructions, self.instruction_files = load_instructions(
            self.root, self.talimat_butcesi
        )

        try:
            self.ctx.permissions = load_permissions(
                self.root,
                mode=MODE_ASK if permission_mode == MODE_PLAN else permission_mode,
            )
        except ValueError as err:
            # Bozuk izin dosyası sessizce daha gevşek bir moda düşmemeli.
            self.io.tool_error(f"İzin yapılandırması okunamadı: {err}")
            self.io.tool_warning(
                "Güvenli varsayılana dönülüyor: her yan etkili araçta onay sorulacak."
            )
            self.ctx.permissions = load_permissions(self.root, mode=MODE_ASK)

        self.oturumlar = SessionStore(self.root, self.io)
        self.devam_edilen = self._devam_et(devam)
        self.oturumlar.baslat(getattr(self.main_model, "name", ""))

        self._install_status_bar()

    def _devam_et(self, devam):
        """--continue verilmişse son oturumu geçmişe yükle.

        Mesajlar API'ye gönderildiği biçimde saklandığı için araç çağrıları
        ve sonuçları da geri geliyor; upstream'in markdown tabanlı geri
        yüklemesi bunları kaybediyordu.
        """
        if not devam:
            return None

        son = self.oturumlar.son()
        if not son:
            self.io.tool_warning("Devam edilecek önceki oturum bulunamadı.")
            return None

        butce = self._prompt_butcesi(DEVAM_PAYI, DEVAM_BUTCESI)
        mesajlar = self.oturumlar.yukle(son, butce)
        if not mesajlar:
            self.io.tool_warning(f"{son.path} boş ya da okunamadı.")
            return None

        self.done_messages = mesajlar
        dusen = son.mesaj_sayisi - len(mesajlar)
        self._devam_ozeti = (
            f"Önceki oturum sürdürülüyor: {son.baslik} ({len(mesajlar)} mesaj"
            + (f", {dusen} tanesi bütçeye sığmadı" if dusen > 0 else "")
            + ")"
        )
        return son

    def _prompt_butcesi(self, pay, tavan, model=None):
        """Bir bloğun karakter bütçesi, modelin penceresine göre.

        Modelin penceresi bilinmiyorsa (özel endpoint'lerde sık) tavan
        kullanılır: tahmin edip çalışan bir kurulumu bozmaktansa eski
        davranışta kalmak yeğ.
        """
        try:
            pencere = ((model or self.main_model).info or {}).get("max_input_tokens")
        except Exception:
            pencere = None
        if not pencere:
            return tavan
        return max(1_000, min(tavan, int(pencere * pay * KARAKTER_BASINA_TOKEN)))

    # ------------------------------------------------------------------
    # Durum çubuğu ve mod değiştirme
    # ------------------------------------------------------------------

    # shift+tab bu sırayla dolaşır.
    MODE_CYCLE = (MODE_PLAN, MODE_ASK, MODE_AUTO)

    # (işaret, ad, renk) — chevron sayısı serbestlik derecesini anlatıyor:
    # plan durakta, onay tek adım, oto serbest.
    #
    # Glyphler Geometric Shapes bloğundan (U+25B6, U+25AE). Claude Code'un
    # kullandığı U+23F5/U+23F8 daha doğru duruyordu ama kurum terminallerinin
    # fontunda yok: kullanıcı prompt'ta boş kutu görüyordu. Bu blok, kutu
    # çizgisi olan hemen her fontta var.
    MODE_LABELS = {
        MODE_PLAN: ("▮▮", "plan modu", "ansiblue"),
        MODE_ASK: ("▶", "onay modu", "ansigreen"),
        MODE_AUTO: ("▶▶", "oto mod", "ansiyellow"),
    }

    # Terminal ya da font bu glyph'leri taşımıyorsa kullanılacak karşılıklar.
    ASCII_MARKERS = {MODE_PLAN: "||", MODE_ASK: ">", MODE_AUTO: ">>"}

    def current_mode(self):
        if self.ctx.plan_mode:
            return MODE_PLAN
        return self.ctx.permissions.mode if self.ctx.permissions else MODE_ASK

    def _install_status_bar(self):
        """io katmanına durum çubuğunu ve shift+tab davranışını bağla."""
        self.io.agent_status = self._status_text
        self.io.agent_cycle_mode = self.cycle_mode

    def _status_text(self):
        """Prompt önekine eklenen kısa mod göstergesi.

        Düz metin döner, biçimli metin değil: prompt öneki aider'in kendi
        stiliyle çiziliyor ve araya renk kodu sokmak satırı bozuyor.
        """
        mode = self.current_mode()
        isaret, ad, _renk = self.MODE_LABELS[mode]
        return f"{self._marker(mode, isaret)} {ad}"

    def _marker(self, mode, isaret):
        """Glyph terminal taşımıyorsa ASCII karşılığına düş."""
        cevrilmis = guvenli(isaret)
        return isaret if cevrilmis == isaret else self.ASCII_MARKERS[mode]

    def cycle_mode(self):
        """shift+tab: plan → onay → oto → plan."""
        mode = self.current_mode()
        yeni = self.MODE_CYCLE[(self.MODE_CYCLE.index(mode) + 1) % len(self.MODE_CYCLE)]

        self.ctx.plan_mode = yeni == MODE_PLAN
        self.plan_mode = self.ctx.plan_mode
        if self.ctx.permissions and yeni != MODE_PLAN:
            self.ctx.permissions.mode = yeni
        return yeni

    def mode_help(self):
        """Üç modun tek satırlık açıklaması; /mod komutu bunu basar."""
        satirlar = []
        for m in self.MODE_CYCLE:
            isaret, ad, _ = self.MODE_LABELS[m]
            aciklama = {
                MODE_PLAN: "salt-okunur — Write, Edit, Bash modele sunulmaz",
                MODE_ASK: "her yan etkili araçta onay sorar",
                MODE_AUTO: "reddedilmedikçe sormaz (yerleşik güvenlik listesi yine geçerli)",
            }[m]
            imza = "→ " if m == self.current_mode() else "  "
            satirlar.append(f"  {imza}{isaret} {ad:10} {aciklama}")
        return "\n".join(satirlar)

    def rebuild_registry(self):
        """MCP sunucuları yeniden başlatıldıktan sonra araç listesini tazele."""
        self.registry = ToolRegistry(self._builtin_tools + self.mcp.tools)
        # Araç kümesi değişti: şema maliyetleri ve verilmiş uyarı geçersiz.
        self._sema_onbellegi = {}
        self._sema_uyarisi_verildi = False

    # ------------------------------------------------------------------
    # Duyuru / prompt
    # ------------------------------------------------------------------

    def get_announcements(self):
        lines = super().get_announcements()
        n = len(self.ctx.skills.skills)
        builtin = [x for x in self.registry.names() if not x.startswith("mcp__")]
        lines.append(f"Araçlar: {', '.join(builtin)}")
        if self._kucuk_pencere():
            lines.append(
                f"Dar pencere ({(self.main_model.info or {}).get('max_input_tokens')} token):"
                f" {', '.join(KUCUK_PENCEREDE_KAPALI)} şemaları sunulmuyor"
            )
        mcp_line = self.mcp.summary()
        if mcp_line:
            lines.append(mcp_line)
        lines.append(
            f"Beceriler: {n} yüklendi" + (f" ({', '.join(self.ctx.skills.skills)})" if n else "")
        )
        if self.instruction_files:
            adlar = ", ".join(p.name for p in self.instruction_files)
            satir = f"Proje talimatları: {adlar}"
            if len(self.instructions) > INSTRUCTION_WARN_CHARS:
                satir += f"  — UZUN ({len(self.instructions)} karakter)"
            lines.append(satir)
            if len(self.instructions) > INSTRUCTION_WARN_CHARS:
                lines.append(
                    "  Küçük modeller uzun talimatı görev sanıp özetleyebilir ve araç"
                    " çağırmaz. Sorun yaşarsan kısalt ya da başka dizinde çalış."
                )
        if self.ctx.memory.notes:
            dusen = self.ctx.memory.dropped(self.bellek_butcesi)
            satir = f"Bellek: {len(self.ctx.memory.notes)} not"
            if dusen:
                satir += f" ({dusen} tanesi bütçe nedeniyle yüklenmedi)"
            lines.append(satir)
        if self.devam_edilen:
            lines.append(self._devam_ozeti)
        if self.offline:
            lines.append("Çevrimdışı mod: sürüm denetimi, analitik ve URL çekme kapalı")
        if self.plan_mode:
            lines.append("Plan modu AÇIK — onay alınana dek dosya değiştirilmez")
        elif self.ctx.permissions.mode == MODE_AUTO:
            lines.append("İzin modu: OTOMATİK — reddedilmeyen her araç sorulmadan çalışır")
        else:
            n_allow = len(self.ctx.permissions.allow)
            extra = f", {n_allow} otomatik izin kuralı" if n_allow else ""
            lines.append(f"İzin modu: onay sorulur{extra}")
        return lines

    def fmt_system_prompt(self, prompt):
        out = super().fmt_system_prompt(prompt)

        catalog = self.ctx.skills.catalog(self.katalog_butcesi)
        if catalog:
            out += self.gpt_prompts.skills_prompt.format(skills=catalog)

        # Proje talimatları ve bellek, becerilerden SONRA eklenir: ikisi de
        # kullanıcının kendi yazdığı kurallardır ve genel yönergeleri ezmelidir.
        if self.instructions:
            out += self.gpt_prompts.instructions_prompt.format(instructions=self.instructions)

        notes = self.ctx.memory.render(self.bellek_butcesi)
        if notes:
            out += self.gpt_prompts.memory_prompt.format(memory=notes)

        if self.ctx.plan_mode:
            out += "\n" + PLAN_MODE_REMINDER

        return out

    def _kucuk_pencere(self):
        """Model penceresi lüks araçların şemasını taşıyamayacak kadar dar mı?"""
        try:
            pencere = (self.main_model.info or {}).get("max_input_tokens")
        except Exception:
            return False
        return bool(pencere) and pencere < KUCUK_PENCERE

    def available_tools(self):
        """Plan modunda yan etkili araçları, dar pencerede lüks araçları çıkar."""
        dar = self._kucuk_pencere()
        names = []
        for name in self.registry.names():
            tool = self.registry.get(name)
            if name == "ExitPlanMode" and not self.ctx.plan_mode:
                continue
            if self.ctx.plan_mode and tool.mutating:
                continue
            if dar and name in KUCUK_PENCEREDE_KAPALI:
                continue
            names.append(name)
        return self._semaya_sigdir(names)

    def _sema_butcesi(self):
        try:
            pencere = (self.main_model.info or {}).get("max_input_tokens")
        except Exception:
            return None
        return int(pencere * SEMA_PAYI) if pencere else None

    def _sema_maliyeti(self, name):
        """Tek bir aracın şemasının token maliyeti; oturum boyunca değişmez."""
        if name in self._sema_onbellegi:
            return self._sema_onbellegi[name]
        try:
            sema = self.registry.schemas(enabled=[name])
            maliyet = self.main_model.token_count(json.dumps(sema, ensure_ascii=False)) or 0
        except Exception:
            maliyet = 0
        self._sema_onbellegi[name] = maliyet
        return maliyet

    def _semaya_sigdir(self, names):
        """Şemalar bütçeyi aşıyorsa MCP araçlarını kes.

        Yerleşik araçlar hiçbir zaman düşmez: onlarsız agent döngüsü çalışmaz.
        Düşen MCP araçları bir kez duyurulur — sessizce kaybolmaları,
        kullanıcının modele "neden bu aracı çağırmadın" diye sormasına yol
        açıyor ve sebebi görünmüyor.
        """
        butce = self._sema_butcesi()
        if not butce:
            return names

        yerlesik = [n for n in names if not n.startswith("mcp__")]
        mcp = [n for n in names if n.startswith("mcp__")]
        if not mcp:
            return names

        toplam = sum(self._sema_maliyeti(n) for n in yerlesik)
        sigan, dusen = [], []
        for n in mcp:
            maliyet = self._sema_maliyeti(n)
            if toplam + maliyet > butce:
                dusen.append(n)
                continue
            toplam += maliyet
            sigan.append(n)

        if dusen and not self._sema_uyarisi_verildi:
            self._sema_uyarisi_verildi = True
            self.io.tool_warning(
                f"Bağlam penceresi dar: {len(dusen)} MCP aracı modele sunulmuyor"
                f" (şema bütçesi {butce:,} token). Düşenler: {', '.join(dusen)}."
                " .mcp.json'u sadeleştir ya da daha geniş pencereli bir model kullan."
            )
        return yerlesik + sigan

    # ------------------------------------------------------------------
    # Ana döngü
    # ------------------------------------------------------------------

    def send_message(self, inp):
        self.event("message_send_starting")
        self.io.llm_started()

        # Normalde init_before_message() kurar; araçlar düzenlemeyi anında diske
        # yazdığı için bu coder'da her giriş noktasında dolu olmak zorunda.
        if self.aider_edited_files is None:
            self.aider_edited_files = set()

        self.cur_messages += [dict(role="user", content=inp)]
        self._oto_sikistir()

        chunks = self.format_messages()
        messages = chunks.all_messages()
        if not self.check_tokens(messages):
            return

        # Bu tur boyunca büyüyecek çalışma mesaj listesi. Araç sonuçları buraya
        # eklenir; kalıcı geçmişe (cur_messages) tur bitiminde yazılır.
        working = list(messages)
        self._otomatik_beceri_ekle(working, inp)
        turn_messages = []
        # Bu mesaj boyunca hiç araç çalıştı mı? Uyarı metnini buna göre
        # seçiyoruz: araç çalıştıysa "hiçbir şey yapmadı" demek yanlış olur.
        arac_calisti = False
        durtuldu = 0
        litellm_ex = LiteLLMExceptions()

        for iteration in range(self.max_iterations):
            if not self._baglami_toparla(working):
                self.io.tool_error(
                    "Bağlam penceresi doldu ve kısaltacak eski araç çıktısı kalmadı."
                    " İşi daha küçük adımlara böl."
                )
                break

            tools = self.registry.schemas(enabled=self.available_tools())

            self.partial_response_content = ""
            self.multi_response_content = ""
            self.mdstream = (
                self.io.get_assistant_mdstream() if (self.show_pretty() and self.stream) else None
            )

            try:
                content, tool_calls = self._one_turn(working, tools)
            except KeyboardInterrupt:
                self.io.tool_warning("\n^C araç döngüsü durduruldu")
                turn_messages.append(dict(role="assistant", content="(kullanıcı kesti)"))
                break
            except litellm_ex.exceptions_tuple() as err:
                ex_info = litellm_ex.get_ex_info(err)
                self.check_and_open_urls(err, ex_info.description)
                break
            except Exception as err:
                self.io.tool_error(f"{err.__class__.__name__}: {err}")
                self.event("message_send_exception", exception=str(err))
                break
            finally:
                if self.mdstream:
                    self.live_incremental_response(True)
                    self.mdstream = None
                self._stop_waiting_spinner()

            assistant_msg = dict(role="assistant", content=content or "")
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            working.append(assistant_msg)
            turn_messages.append(assistant_msg)

            if not tool_calls:
                # Sessiz bitiş kullanıcıya "bir şey oldu ama göremiyorum"
                # hissi veriyor. Ama araç çalıştıysa "hiçbir şey yapmadı"
                # demek yanlış olur — iş yapıldı, yalnızca özetlenmedi.
                if not (content or "").strip():
                    # Zayıf modeller araç sonucundan sonra boş yanıt vermeye
                    # eğilimli. İlk boşlukta pes etmek işi yarıda bırakıyor;
                    # bir kez dürtmek çoğu zaman devam ettiriyor. Bir kerelik,
                    # yoksa boş-dürtme-boş döngüsü oluşur.
                    if durtuldu < MAX_BOS_DURTME:
                        durtuldu += 1
                        working.pop()  # boş assistant mesajını geçmişe koyma
                        turn_messages.pop()
                        durtme = (
                            "Araç çıktısı yukarıda. Şimdi ya sonucu birkaç cümleyle"
                            " özetle ya da bir sonraki aracı çağır."
                            if arac_calisti
                            else "İsteği yerine getirmek için uygun aracı çağır."
                        )
                        working.append(dict(role="user", content=durtme))
                        self.io.tool_warning("Model boş döndü, bir kez daha deneniyor.")
                        continue

                    if arac_calisti:
                        self.io.tool_warning(
                            "Model sonucu özetlemedi. Araç çıktısı yukarıda."
                        )
                    else:
                        self.io.tool_warning(
                            "Model boş yanıt verdi ve hiç araç çağırmadı. İsteği daha "
                            "kısa ve tek adımlı yazmayı dene."
                        )
                break

            arac_calisti = True

            for call in tool_calls:
                result = self._run_tool_call(call)
                tool_msg = dict(
                    role="tool",
                    tool_call_id=call["id"],
                    name=call["function"]["name"],
                    content=result,
                )
                working.append(tool_msg)
                turn_messages.append(tool_msg)
        else:
            self.io.tool_warning(f"{self.max_iterations} araç turu sınırına ulaşıldı, duruldu.")

        self.io.tool_output()
        self.show_usage_report()

        self.cur_messages += turn_messages
        self.oturumlar.ekle([dict(role="user", content=inp)] + turn_messages)
        self._finish_turn()

        # Coder.run_one bu metodu list() ile tüketiyor, yani üreteç olmak zorunda.
        # Akış çıktısını doğrudan io'ya yazdığımız için yield edecek bir şeyimiz yok.
        return
        yield

    def _otomatik_beceri_ekle(self, working, inp):
        """İsteğe uyan beceriyi bu tur için bağlama koy.

        Modelin Skill aracını kendiliğinden çağırmasını beklemek çalışmıyor.
        Ölçüldü: 14 beceri yüklüyken gemma4:e4b "skyup sunucusuna bağlan ve OS
        güncel mi diye bak" isteğinde Skill'i bir kez bile çağırmadı, doğrudan
        Ssh denedi ve boş döndü. Katalog sistem promptunda duruyor ama 4B
        sınıfı bir model onlarca satırdan doğru olanı seçemiyor.

        Beceri gövdesi kalıcı geçmişe değil, YALNIZCA bu turun mesaj listesine
        giriyor: her turda tekrar tekrar birikirse bağlam beceri metinleriyle
        dolar. Eşleşme sürerse bir sonraki turda yeniden eklenir.
        """
        if not self.otomatik_beceri or not self.ctx.skills:
            return None

        eslesme = self.ctx.skills.eslestir(inp, limit=1)
        if not eslesme:
            return None

        skill, vurus = eslesme[0]
        blok = self.gpt_prompts.auto_skill_prompt.format(
            name=skill.name,
            body=skill.render(self.beceri_butcesi),
            triggers=", ".join(vurus),
        )

        # Ayrı bir mesaj yerine son kullanıcı mesajına iliştiriliyor: arka
        # arkaya iki user mesajı bazı sohbet şablonlarını bozuyor.
        for i in range(len(working) - 1, -1, -1):
            if working[i].get("role") == "user":
                working[i] = dict(working[i])
                working[i]["content"] = (working[i].get("content") or "") + blok
                break
        else:
            return None

        self.io.tool_output(f"Beceri otomatik yüklendi: {skill.name} ({', '.join(vurus)})")
        return skill

    def _baglam_siniri(self):
        """Araç döngüsünde aşılmaması gereken karakter sayısı."""
        try:
            pencere = (self.main_model.info or {}).get("max_input_tokens")
        except Exception:
            pencere = None
        if not pencere:
            return None
        return int(pencere * DOLULUK_ESIGI * KARAKTER_BASINA_TOKEN)

    def _oto_sikistir(self):
        """Turlar arası biriken geçmişi, pencere dolmadan önce özetle.

        `_baglami_toparla` yalnızca tek bir mesajın araç döngüsü içinde
        işliyor; turlar arasında biriken geçmişe dokunmuyor. Dokunması da
        gerekmiyordu: aider normalde `move_back_cur_messages` ile geçmişi
        `done_messages`'a taşıyıp upstream özetleyicisini tetikliyor. Ama
        agent modunda o çağrı yalnızca dosya DÜZENLENDİĞİNDE yapılıyor —
        teşhis oturumlarının çoğu hiçbir dosyayı değiştirmiyor, dolayısıyla
        geçmiş hiç özetlenmeden sınırsız büyüyordu.
        """
        if not self.otomatik_ozet:
            return
        sinir = self._baglam_siniri()
        if not sinir:
            return

        mesajlar = self.done_messages + self.cur_messages
        if sikistirma.toplam_karakter(mesajlar) <= sinir:
            return

        self.io.tool_warning("Bağlam doluyor, geçmiş otomatik özetleniyor.")
        self.sikistir()

    def _ozet_modeli(self):
        """Özetleme hangi modelde yapılsın?

        Özet çıkarmak bir metin sıkıştırma işi; asıl modelin muhakemesine
        ihtiyacı yok. Ayrı bir zayıf model tanımlıysa (`--weak-model`) oraya
        gidiyor. Kazanç iki yönlü: dökümün asıl modelin dar penceresine sığması
        gerekmiyor, ve zayıf model daha büyük pencereli olabiliyor.
        """
        zayif = getattr(self.main_model, "weak_model", None)
        if zayif is not None and zayif is not self.main_model:
            return zayif
        return self.main_model

    def sikistir(self, korunan_tur=sikistirma.KORUNAN_TUR):
        """Geçmişi özetle ve yerine koy; özetlenen mesaj sayısını döndür.

        Sıfır dönmesi bir hata değil: özetlenecek kadar geçmiş yoktu ya da
        model özet üretemedi. İki durumda da eski geçmiş olduğu gibi kalır —
        yarım bir özetle değiştirmek, hiç özetlememekten kötü.
        """
        mesajlar = self.done_messages + self.cur_messages
        kes = sikistirma.kesme_noktasi(mesajlar, korunan_tur)
        if kes <= 0:
            self.io.tool_output("Özetlenecek kadar geçmiş yok.")
            return 0

        onceki = sikistirma.toplam_karakter(mesajlar)
        ozetleyici = self._ozet_modeli()
        nerede = "" if ozetleyici is self.main_model else f" ({ozetleyici.name} ile)"
        self.io.tool_output(f"{kes} mesaj özetleniyor{nerede}…")

        butce = self._prompt_butcesi(DOKUM_PAYI, sikistirma.DOKUM_TAVANI, ozetleyici)
        try:
            metin = ozetleyici.simple_send_with_retries(
                sikistirma.istem(sikistirma.dokum(mesajlar[:kes], tavan=butce))
            )
        except Exception as err:
            self.io.tool_error(f"Özetleme başarısız, geçmiş olduğu gibi bırakıldı: {err}")
            return 0

        if not (metin or "").strip():
            self.io.tool_error("Model boş özet döndürdü, geçmiş olduğu gibi bırakıldı.")
            return 0

        self.done_messages = sikistirma.uygula(mesajlar, metin, kes)
        self.cur_messages = []

        sonraki = sikistirma.toplam_karakter(self.done_messages)
        self.io.tool_output(
            f"Bağlam özetlendi: {onceki:,} → {sonraki:,} karakter"
            f" (son {korunan_tur} tur aynen korundu)."
        )
        if self.oturumlar.path:
            self.io.tool_output(f"Tam kayıt duruyor: {self.oturumlar.path}")
        return kes

    def _baglami_toparla(self, working):
        """Bağlam dolmak üzereyse en eski araç çıktılarını kısalt.

        Devam edilebiliyorsa True, yer açılamadıysa False döner.

        Kısaltılan yalnızca `role="tool"` mesajlarının gövdesi; mesajın
        kendisi ve `tool_call_id`'si yerinde kalıyor. Mesajı tümden atmak
        `tool_calls` taşıyan assistant mesajını yanıtsız bırakır ve endpoint
        isteği reddeder.

        Sözlükler `turn_messages` ile paylaşımlı, yani kısaltma kalıcı
        geçmişe ve oturum kaydına da yansıyor. Bu bilinçli: aynı devasa çıktı
        bir sonraki turda ve --continue ile geri yüklemede yine yer yiyecekti.
        """
        sinir = self._baglam_siniri()

        def toplam():
            return sum(len(str(msg.get("content") or "")) for msg in working)

        # DİKKAT: karakter hesabı "sığıyor" dese bile token doğrulaması
        # atlanmıyor. Erken dönmek tam da yakalanması gereken durumu
        # kaçırıyordu: kötü tokenlaşan çıktıda 27.693 karakter sınırın altında
        # ama 15.293 token tavanın üstünde.
        if not sinir or toplam() <= sinir:
            return self._token_ile_dogrula(working)

        kisaltilan = 0
        son_kademe = 0
        for kademe, koruma in enumerate(KORUMA_KADEMELERI):
            if toplam() <= sinir:
                break
            son_kademe = kademe
            for msg in working[: len(working) - koruma]:
                if msg.get("role") != "tool":
                    continue
                icerik = str(msg.get("content") or "")
                if len(icerik) <= KISALTMA_ESIGI:
                    continue
                msg["content"] = (
                    f"(araç çıktısı bağlam için kısaltıldı, {len(icerik)} karakterdi)\n"
                    + icerik[:KISALTMA_ESIGI]
                )
                kisaltilan += 1
                if toplam() <= sinir:
                    break

        if kisaltilan:
            nere = " (son adımların çıktısı dahil)" if son_kademe else ""
            self.io.tool_warning(
                f"Bağlam doluyordu: {kisaltilan} araç çıktısı kısaltıldı{nere}."
            )

        return self._token_ile_dogrula(working)

    def _token_tavani(self):
        """Gerçek token cinsinden aşılmaması gereken sınır."""
        try:
            pencere = (self.main_model.info or {}).get("max_input_tokens")
        except Exception:
            return None
        return int(pencere * DOLULUK_ESIGI) if pencere else None

    def _en_buyugu_kirp(self, working):
        """En büyük araç çıktısını yarıya indir; kırpılacak bir şey yoksa False."""
        hedef, boy = None, 0
        for msg in working:
            if msg.get("role") != "tool":
                continue
            n = len(str(msg.get("content") or ""))
            if n > boy:
                hedef, boy = msg, n
        if hedef is None or boy <= TOKEN_KIRPMA_TABANI:
            return False

        icerik = str(hedef["content"])
        # Üst üste kırpmada başlık birikmesin.
        if icerik.startswith("(araç çıktısı"):
            icerik = icerik.split("\n", 1)[-1]
        hedef["content"] = (
            f"(araç çıktısı bağlam için kısaltıldı, {boy} karakterdi)\n"
            + icerik[: len(icerik) // 2]
        )
        return True

    def _token_ile_dogrula(self, working):
        """Karakter kırpmasından sonra tokenizer'la doğrula, gerekirse kırpmayı sürdür.

        Karakter/token oranı bir tahmin; sınıra yakınken tutmuyor. Sayım
        yapılamıyorsa (özel endpoint'lerde olabiliyor) karakter hesabına
        güvenip devam ediliyor — sayamadığı için işi durdurmak yanlış olur.
        """
        tavan = self._token_tavani()
        if not tavan:
            return True

        for _ in range(TOKEN_KIRPMA_DENEMESI):
            try:
                sayim = self.main_model.token_count(working)
            except Exception:
                return True
            if not sayim:
                return True
            if sayim <= tavan:
                return True
            if not self._en_buyugu_kirp(working):
                return False

        try:
            return (self.main_model.token_count(working) or 0) <= tavan
        except Exception:
            return True

    def _one_turn(self, messages, tools):
        """Modele bir istek at, (metin, tool_calls) döndür."""
        if self.show_pretty():
            from aider.waiting import WaitingSpinner

            self.waiting_spinner = WaitingSpinner("Waiting for " + self.main_model.name)
            self.waiting_spinner.start()

        self.io.log_llm_history("TO LLM", json.dumps(messages, default=str)[:20000])

        _hash, completion = self.main_model.send_completion(
            messages,
            tools or None,
            self.stream,
            self.temperature,
        )

        if self.stream:
            content, tool_calls = self._consume_stream(completion)
        else:
            content, tool_calls = self._consume_response(completion)

        try:
            self.calculate_and_show_tokens_and_cost(messages, completion)
        except Exception:
            # Maliyet hesabı bilgilendirme amaçlı; başarısız olması turu bozmamalı.
            pass

        self.io.log_llm_history("LLM RESPONSE", content or "(araç çağrısı)")
        return content, tool_calls

    def _consume_response(self, completion):
        if not completion.choices:
            raise Exception(f"Modelden boş yanıt: {completion}")

        msg = completion.choices[0].message
        content = getattr(msg, "content", None) or ""
        raw_calls = getattr(msg, "tool_calls", None) or []

        calls = []
        for i, tc in enumerate(raw_calls):
            calls.append(
                dict(
                    id=getattr(tc, "id", None) or f"call_{i}",
                    type="function",
                    function=dict(
                        name=tc.function.name,
                        arguments=tc.function.arguments or "{}",
                    ),
                )
            )

        if content:
            self.partial_response_content = content
            self.io.assistant_output(content, pretty=self.show_pretty())

        return content, calls

    def _consume_stream(self, completion):
        """Akışı tüket; metni canlı göster, tool_call parçalarını index'e göre birleştir."""
        acc = {}
        got_any = False

        for chunk in completion:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            for tc in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc, "index", 0) or 0
                slot = acc.setdefault(
                    idx, dict(id=None, type="function", function=dict(name="", arguments=""))
                )
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["function"]["name"] += fn.name
                    if getattr(fn, "arguments", None):
                        slot["function"]["arguments"] += fn.arguments
                got_any = True

            text = getattr(delta, "content", None)
            if text:
                got_any = True
                self.partial_response_content += text
                if self.mdstream:
                    self.live_incremental_response(False)
                else:
                    self.io.ai_output(text)

            if got_any:
                self._stop_waiting_spinner()

        calls = []
        for idx in sorted(acc):
            slot = acc[idx]
            if not slot["function"]["name"]:
                continue
            slot["id"] = slot["id"] or f"call_{idx}"
            slot["function"]["arguments"] = slot["function"]["arguments"] or "{}"
            calls.append(slot)

        return self.partial_response_content, calls

    def _run_tool_call(self, call):
        name = call["function"]["name"]
        raw_args = call["function"].get("arguments") or "{}"

        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError as err:
            return (
                f"Hata: {name} argümanları geçerli JSON değil ({err}). " f"Gelen: {raw_args[:500]}"
            )

        if name not in self.registry:
            return f"Hata: '{name}' diye bir araç yok."

        tool = self.registry.get(name)
        if self.ctx.plan_mode and tool.mutating:
            return (
                f"Hata: plan modunda {name} kullanılamaz. Önce araştırmanı bitir ve "
                "planı ExitPlanMode ile sun."
            )

        self._show_tool_call(name, args)
        result = self.registry.run(name, args, self.ctx)
        self.plan_mode = self.ctx.plan_mode

        # Sonuç modele gidiyor ama kullanıcıya da görünmeli. Görünmezse model
        # zayıf olduğunda ekranda yalnızca çağrı satırı kalıyor: komut çalıştı,
        # veri geldi, ama kullanıcı hiçbir şey görmüyor.
        self._show_tool_result(name, result)

        return result

    def _show_tool_result(self, name, result):
        """Araç çıktısını kullanıcıya özetleyerek göster."""
        if not isinstance(result, str) or not result.strip():
            return

        if result.startswith("Hata:"):
            self.io.tool_error(f"    {result.splitlines()[0]}")
            return

        if name in KENDI_BASAN_ARACLAR:
            return

        satirlar = result.splitlines()
        limit = 1 if name in OZET_SATIRI_YETER else RESULT_PREVIEW_LINES

        for satir in satirlar[:limit]:
            self.io.tool_output(f"    {satir}")

        kalan = len(satirlar) - limit
        if kalan > 0:
            self.io.tool_output(f"    ... {kalan} satır daha (toplam {len(satirlar)})")

    def _show_tool_call(self, name, args):
        """Araç çağrısını kullanıcıya tek satırda özetle."""
        if name in ("Read", "Write", "Edit"):
            detail = args.get("file_path", "")
        elif name == "Bash":
            detail = args.get("command", "")
        elif name == "Ssh":
            detail = f"{args.get('host', '?')}: {args.get('command', '')}"
        elif name in ("Grep", "Glob"):
            detail = args.get("pattern", "")
        elif name == "Skill":
            detail = args.get("skill", "")
        elif name == "TodoWrite":
            detail = f"{len(args.get('todos', []))} görev"
        else:
            detail = ""

        detail = detail.replace("\n", " ")
        if len(detail) > 90:
            detail = detail[:90] + "..."
        self.io.tool_output(f"  {self._ok()} {name}({detail})")

    def _ok(self):
        """Araç çağrısı imi; terminal taşımıyorsa ASCII'ye düş."""
        return guvenli("→")

    def _finish_turn(self):
        """Tur sonunda aider'ın git/lint/test makinesini devreye sok."""
        edited = self.aider_edited_files or set()
        if not edited:
            return

        saved_message = self.auto_commit(edited)
        if not saved_message:
            saved_message = self.gpt_prompts.files_content_gpt_edits_no_repo
        self.move_back_cur_messages(saved_message)

        if self.auto_lint:
            lint_errors = self.lint_edited(edited)
            self.auto_commit(edited, context="Ran the linter")
            self.lint_outcome = not lint_errors
            if lint_errors and self.io.confirm_ask("Lint hatalarını düzeltmeyi dene?"):
                self.reflected_message = lint_errors
                return

        if self.auto_test:
            test_errors = self.commands.cmd_test(self.test_cmd)
            self.test_outcome = not test_errors
            if test_errors and self.io.confirm_ask("Test hatalarını düzeltmeyi dene?"):
                self.reflected_message = test_errors

    # Araçlar düzenlemeleri anında diske yazdığı için aider'ın edit-block
    # ayrıştırma yolu bu coder'da kullanılmaz.
    def get_edits(self, mode="update"):
        return []

    def apply_edits(self, edits):
        pass
