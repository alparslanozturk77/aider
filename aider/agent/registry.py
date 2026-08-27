"""Araç kayıt defteri ve çalıştırma bağlamı."""

import json
import traceback

from .permissions import ALLOW, DENY, suggest_rule


class ToolError(Exception):
    """Modele geri bildirilecek, kurtarılabilir araç hatası."""


class ToolContext:
    """Araçların ihtiyaç duyduğu her şeyi taşıyan bağlam nesnesi.

    Coder'ın tamamını araçlara vermek yerine, araçların gerçekten kullandığı
    yüzeyi burada topluyoruz; böylece test etmek ve upstream değişikliklerine
    dayanıklı kalmak kolaylaşıyor.
    """

    def __init__(self, coder):
        self.coder = coder
        self.io = coder.io
        self.root = coder.root
        self.todos = None  # TodoList, AgentCoder tarafından atanır
        self.skills = None  # SkillLibrary, AgentCoder tarafından atanır
        self.plan_mode = False
        self.approved_plan = None
        # İzin kuralları; AgentCoder tarafından atanır.
        self.permissions = None
        # Bash için oturum boyunca hatırlanan çalışma dizini
        self.cwd = coder.root
        # confirm() çağrısı sırasında değerlendirilen araç çağrısının argümanları.
        # Araçlar confirm'e yalnızca bir konu metni verdiği için, izin kurallarının
        # ihtiyaç duyduğu ham argümanları buradan taşıyoruz.
        self._pending_args = {}

    def confirm(self, tool_name, subject, question=None, args=None):
        """Yan etkili bir araç çağrısı için izin kararı ver.

        Kural tabanlı izin sistemi önce değerlendirilir: reddedilen çağrılar
        kullanıcıya hiç sorulmadan engellenir, izinli olanlar sorulmadan geçer.
        Karar 'ask' ise kullanıcıya sorulur ve 'bir daha sorma' yanıtı oturumluk
        bir izin kuralına dönüştürülür.
        """
        args = args if args is not None else self._pending_args

        if self.permissions:
            decision = self.permissions.decide(tool_name, args, mutating=True)
            if decision == DENY:
                self.io.tool_error(f"İzin reddedildi: {tool_name} — {subject}")
                return False
            if decision == ALLOW:
                return True

        question = question or f"{tool_name} çalıştırılsın mı?"
        res = self.io.confirm_ask(question, subject=subject, allow_never=True)

        # "Bir daha sorma" yanıtı aider'da False döner ve soru never_prompts'a
        # yazılır; o kayıt (soru, konu) çiftine bağlı olduğu için desen bazlı
        # çalışmaz. Kendi kural listemize çevirip gerçekten kullanışlı yapıyoruz.
        if self.io.never_prompts and (question, subject) in self.io.never_prompts:
            rule = suggest_rule(tool_name, args)
            self.io.never_prompts.discard((question, subject))
            if self.permissions:
                self.permissions.add_session_allow(rule)
                self.io.tool_output(f"Bu oturum için izin kuralı eklendi: {rule}")
            return True

        return bool(res)


class ToolRegistry:
    """Araçları isimden çözer, şemalarını üretir ve çalıştırır."""

    def __init__(self, tools):
        self._tools = {t.name: t for t in tools}

    def __contains__(self, name):
        return name in self._tools

    def get(self, name):
        return self._tools.get(name)

    def names(self):
        return list(self._tools)

    def schemas(self, enabled=None):
        """OpenAI tool-calling formatında şema listesi döndür."""
        out = []
        for name, tool in self._tools.items():
            if enabled is not None and name not in enabled:
                continue
            out.append(
                dict(
                    type="function",
                    function=dict(
                        name=tool.name,
                        description=tool.description,
                        parameters=tool.parameters,
                    ),
                )
            )
        return out

    def run(self, name, args, ctx):
        """Aracı çalıştır, her zaman modele verilebilir bir string döndür.

        Araç hataları istisna olarak yükseltilmez; modelin kendini
        düzeltebilmesi için metin olarak geri verilir.
        """
        tool = self._tools.get(name)
        if not tool:
            return f"Hata: '{name}' diye bir araç yok. Mevcut araçlar: {', '.join(self.names())}"

        if not isinstance(args, dict):
            return f"Hata: {name} argümanları JSON nesnesi olmalı, gelen: {type(args).__name__}"

        # İzin kuralları ham argümanlara bakar; araçlar confirm()'e yalnızca
        # okunabilir bir konu metni verdiği için argümanları bağlama taşıyoruz.
        ctx._pending_args = args

        try:
            result = tool.run(ctx, **args)
        except ToolError as err:
            return f"Hata: {err}"
        except TypeError as err:
            return f"Hata: {name} için geçersiz argümanlar: {err}"
        except Exception as err:
            if ctx.coder.verbose:
                ctx.io.tool_warning(traceback.format_exc())
            return f"Hata: {name} çalışırken beklenmeyen hata: {err.__class__.__name__}: {err}"

        if result is None:
            return "(araç çıktı üretmedi)"
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return str(result)
