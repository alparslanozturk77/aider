"""Claude Code tarzı görev listesi takibi."""

from .tools import Tool
from .registry import ToolError

STATUSES = ("pending", "in_progress", "completed")

_MARK = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}


class TodoList:
    def __init__(self):
        self.items = []

    def replace(self, todos):
        self.items = todos

    def render(self):
        if not self.items:
            return "(görev listesi boş)"
        lines = []
        for t in self.items:
            status = t.get("status", "pending")
            text = t.get("activeForm") if status == "in_progress" else t.get("content")
            lines.append(f"{_MARK.get(status, '[ ]')} {text}")
        return "\n".join(lines)

    def summary(self):
        done = sum(1 for t in self.items if t.get("status") == "completed")
        return f"{done}/{len(self.items)} tamamlandı"


class TodoWriteTool(Tool):
    name = "TodoWrite"
    description = (
        "Görev listesini oluşturur ve günceller. Çok adımlı işlerde kullan: işe "
        "başlarken tüm adımları 'pending' olarak yaz, bir adıma başlarken onu "
        "'in_progress' yap (aynı anda yalnızca bir tane), bitirince hemen "
        "'completed' işaretle. Her çağrı listenin TAMAMINI değiştirir."
    )
    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Görev listesinin tamamı",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Görev, emir kipiyle: 'Testleri çalıştır'"},
                        "activeForm": {"type": "string", "description": "Sürüyor hali: 'Testler çalıştırılıyor'"},
                        "status": {"type": "string", "enum": list(STATUSES)},
                    },
                    "required": ["content", "activeForm", "status"],
                },
            }
        },
        "required": ["todos"],
    }

    def run(self, ctx, todos):
        if not isinstance(todos, list):
            raise ToolError("todos bir dizi olmalı")

        cleaned = []
        for i, t in enumerate(todos):
            if not isinstance(t, dict):
                raise ToolError(f"todos[{i}] bir nesne olmalı")
            status = t.get("status", "pending")
            if status not in STATUSES:
                raise ToolError(f"todos[{i}].status geçersiz: {status}. Geçerli: {', '.join(STATUSES)}")
            content = t.get("content")
            if not content:
                raise ToolError(f"todos[{i}].content zorunlu")
            cleaned.append(
                dict(content=content, activeForm=t.get("activeForm") or content, status=status)
            )

        active = [t for t in cleaned if t["status"] == "in_progress"]
        if len(active) > 1:
            raise ToolError(
                f"aynı anda yalnızca bir görev 'in_progress' olabilir, {len(active)} tane var"
            )

        ctx.todos.replace(cleaned)
        ctx.io.tool_output("\n" + ctx.todos.render() + "\n")
        return f"Görev listesi güncellendi ({ctx.todos.summary()})."
