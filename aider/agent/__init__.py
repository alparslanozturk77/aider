"""Claude Code benzeri agentic katman.

Bu paket aider'a gerçek bir tool-calling döngüsü, SKILL.md tabanlı beceri
sistemi ve plan/TODO takibi ekler. Upstream aider dosyalarına mümkün olan en
az dokunuşla çalışacak şekilde ayrı tutulmuştur.
"""

from .registry import ToolRegistry, ToolContext, ToolError
from .skills import SkillLibrary, Skill
from .todo import TodoList

__all__ = [
    "ToolRegistry",
    "ToolContext",
    "ToolError",
    "SkillLibrary",
    "Skill",
    "TodoList",
]
