"""Araç kayıt defteri ve çalıştırma bağlamı."""

import json
import traceback


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
        # Bu oturumda kullanıcının "hep izin ver" dediği araç adları
        self.always_allow = set()
        # Bash için oturum boyunca hatırlanan çalışma dizini
        self.cwd = coder.root

    def confirm(self, tool_name, subject, question=None):
        """Yan etkili araçlar için kullanıcı onayı al.

        --yes-always ile çalışıldığında aider'ın io katmanı zaten otomatik
        onaylar; burada ayrıca oturum-içi "hep izin ver" kaydı tutuyoruz.
        """
        if tool_name in self.always_allow:
            return True

        question = question or f"{tool_name} çalıştırılsın mı?"
        ok = self.io.confirm_ask(
            question,
            subject=subject,
            allow_never=True,
        )
        return bool(ok)


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
