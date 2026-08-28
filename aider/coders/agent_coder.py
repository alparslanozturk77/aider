"""Gerçek tool-calling döngüsüyle çalışan agentic coder.

Aider'ın klasik akışı tek atımlıdır: bağlamın tamamını gönder, yanıttaki edit
bloklarını uygula, dur. AgentCoder bunun yerine Claude Code'daki gibi bir döngü
kurar: model araç çağırır, sonucu görür, tekrar karar verir; iş bitene kadar.
"""

import json
import sys

from aider.agent.plan import PLAN_MODE_REMINDER, ExitPlanModeTool
from aider.agent.mcp import MCPManager
from aider.agent.memory import (
    INSTRUCTION_WARN_CHARS,
    HatirlaTool,
    MemoryStore,
    default_memory_roots,
    load_instructions,
)
from aider.agent.permissions import MODE_ASK, MODE_AUTO, MODE_PLAN, load_permissions
from aider.agent.registry import ToolContext, ToolRegistry
from aider.agent.skills import SkillLibrary, SkillTool, default_skill_roots
from aider.agent.ssh_tool import SshTool
from aider.agent.todo import TodoList, TodoWriteTool
from aider.agent.tools import (
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


class AgentCoder(Coder):
    """Claude Code tarzı araç döngüsü."""

    edit_format = "agent"
    gpt_prompts = AgentPrompts()

    def __init__(self, *args, **kwargs):
        self.plan_mode = kwargs.pop("plan_mode", False)
        self.max_iterations = kwargs.pop("max_iterations", DEFAULT_MAX_ITERATIONS)
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
        self.mcp = MCPManager(self.io, self.root)
        mcp_tools = self.mcp.load()
        for err in self.mcp.errors:
            self.io.tool_error(f"MCP: {err}")

        self._builtin_tools = builtin_tools
        self.registry = ToolRegistry(builtin_tools + mcp_tools)

        self.ctx = ToolContext(self)
        self.ctx.todos = TodoList()
        self.ctx.skills = SkillLibrary(default_skill_roots(self.root))
        self.ctx.memory = MemoryStore(default_memory_roots(self.root))
        self.ctx.plan_mode = self.plan_mode

        self.instructions, self.instruction_files = load_instructions(self.root)

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

        self._install_status_bar()

    # ------------------------------------------------------------------
    # Durum çubuğu ve mod değiştirme
    # ------------------------------------------------------------------

    # shift+tab bu sırayla dolaşır.
    MODE_CYCLE = (MODE_PLAN, MODE_ASK, MODE_AUTO)

    # (işaret, ad, renk) — Claude Code'un durum satırına yakın kalsın diye
    # chevron sayısı serbestlik derecesini anlatıyor: plan durakta, onay tek
    # adım, oto serbest.
    MODE_LABELS = {
        MODE_PLAN: ("⏸", "plan modu", "ansiblue"),
        MODE_ASK: ("⏵", "onay modu", "ansigreen"),
        MODE_AUTO: ("⏵⏵", "oto mod", "ansiyellow"),
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
        """Glyph terminalin kodlamasında yoksa ASCII karşılığına düş."""
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        try:
            isaret.encode(enc)
        except (UnicodeEncodeError, LookupError):
            return self.ASCII_MARKERS[mode]
        return isaret

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

    # ------------------------------------------------------------------
    # Duyuru / prompt
    # ------------------------------------------------------------------

    def get_announcements(self):
        lines = super().get_announcements()
        n = len(self.ctx.skills.skills)
        builtin = [x for x in self.registry.names() if not x.startswith("mcp__")]
        lines.append(f"Araçlar: {', '.join(builtin)}")
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
            dusen = self.ctx.memory.dropped()
            satir = f"Bellek: {len(self.ctx.memory.notes)} not"
            if dusen:
                satir += f" ({dusen} tanesi bütçe nedeniyle yüklenmedi)"
            lines.append(satir)
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

        catalog = self.ctx.skills.catalog()
        if catalog:
            out += self.gpt_prompts.skills_prompt.format(skills=catalog)

        # Proje talimatları ve bellek, becerilerden SONRA eklenir: ikisi de
        # kullanıcının kendi yazdığı kurallardır ve genel yönergeleri ezmelidir.
        if self.instructions:
            out += self.gpt_prompts.instructions_prompt.format(instructions=self.instructions)

        notes = self.ctx.memory.render()
        if notes:
            out += self.gpt_prompts.memory_prompt.format(memory=notes)

        if self.ctx.plan_mode:
            out += "\n" + PLAN_MODE_REMINDER

        return out

    def available_tools(self):
        """Plan modunda yan etkili araçları listeden çıkar."""
        names = []
        for name in self.registry.names():
            tool = self.registry.get(name)
            if name == "ExitPlanMode" and not self.ctx.plan_mode:
                continue
            if self.ctx.plan_mode and tool.mutating:
                continue
            names.append(name)
        return names

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

        chunks = self.format_messages()
        messages = chunks.all_messages()
        if not self.check_tokens(messages):
            return

        # Bu tur boyunca büyüyecek çalışma mesaj listesi. Araç sonuçları buraya
        # eklenir; kalıcı geçmişe (cur_messages) tur bitiminde yazılır.
        working = list(messages)
        turn_messages = []
        litellm_ex = LiteLLMExceptions()

        for iteration in range(self.max_iterations):
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
                break

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
        self._finish_turn()

        # Coder.run_one bu metodu list() ile tüketiyor, yani üreteç olmak zorunda.
        # Akış çıktısını doğrudan io'ya yazdığımız için yield edecek bir şeyimiz yok.
        return
        yield

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

        # Hata modele geri gidiyor ama kullanıcıya da görünmeli: aksi hâlde
        # model bir aracı yanlış çağırdığında ekranda yalnızca çağrı satırı
        # kalıyor ve neden hiçbir şey olmadığı anlaşılmıyor.
        if isinstance(result, str) and result.startswith("Hata:"):
            self.io.tool_error(f"    {result.splitlines()[0]}")

        return result

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
        self.io.tool_output(f"  → {name}({detail})")

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
