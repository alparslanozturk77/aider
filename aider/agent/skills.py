"""SKILL.md tabanlı beceri sistemi.

Claude Code'daki gibi: her beceri bir klasör, içinde YAML frontmatter'lı bir
SKILL.md. Sistem promptuna yalnızca ad + açıklama enjekte edilir (ucuz); gövde
ancak model beceriyi Skill aracıyla çağırınca yüklenir (progressive disclosure).

Aranan yerler, öncelik sırasıyla:
  1. <proje>/.aider/skills/   kişisel, .gitignore'daki .aider* ile depo dışında
  2. <proje>/aider-skills/    takımla paylaşılan, depoya girer
  3. ~/.aider/skills/         tüm projelerde geçerli kişisel beceriler
  4. AIDER_SKILLS_PATH ortam değişkenindeki iki nokta ile ayrılmış dizinler

Sıra bilinçli: aynı adlı bir beceri hem kişisel hem paylaşılan dizinde varsa
kişisel olan kazanır, yani paylaşılan bir beceriyi lokalde geçici olarak
ezebilirsin.
"""

import os
import re
from pathlib import Path

from .registry import ToolError
from .tools import Tool, _truncate

SKILL_FILE = "SKILL.md"
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def _parse_frontmatter(text):
    """Minimal YAML frontmatter ayrıştırıcı (name/description düzeyinde).

    PyYAML'a bağımlılık eklememek için kasıtlı olarak basit tutuldu; beceri
    frontmatter'ı yalnızca düz `anahtar: değer` çiftleri içerir.
    """
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text

    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip().strip("'\"")
        meta[key.strip()] = val
    return meta, m.group(2)


class Skill:
    def __init__(self, name, description, path, body):
        self.name = name
        self.description = description
        self.path = path
        self.body = body

    def render(self):
        """Modele verilecek tam beceri metni."""
        header = f"# Beceri: {self.name}\n\nKaynak: {self.path}\n"
        return _truncate(f"{header}\n{self.body.strip()}")


class SkillLibrary:
    def __init__(self, roots):
        self.roots = [Path(r) for r in roots]
        self.skills = {}
        self.load()

    def load(self):
        self.skills = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for skill_md in sorted(root.glob(f"*/{SKILL_FILE}")):
                skill = self._read(skill_md)
                if skill and skill.name not in self.skills:
                    # Önce gelen kök kazanır: proje becerisi kullanıcı becerisini ezer.
                    self.skills[skill.name] = skill
        return self.skills

    def _read(self, path):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        meta, body = _parse_frontmatter(text)
        name = meta.get("name") or path.parent.name
        desc = meta.get("description", "").strip()
        if not desc:
            return None  # açıklamasız beceri tetiklenemez, atla
        return Skill(name, desc, path, body)

    def catalog(self):
        """Sistem promptuna gömülecek kısa liste."""
        if not self.skills:
            return ""
        lines = [f"- {s.name}: {s.description}" for s in self.skills.values()]
        return "\n".join(lines)

    def get(self, name):
        return self.skills.get(name)


# Depoya girebilen, paylaşılan beceri dizini. Gizli dizin değil, çünkü
# .gitignore'daki .aider* kuralı .aider/skills/ altını depo dışında bırakıyor.
SHARED_SKILLS_DIR = "aider-skills"


def default_skill_roots(project_root):
    project_root = Path(project_root)
    roots = [
        project_root / ".aider" / "skills",
        project_root / SHARED_SKILLS_DIR,
        Path.home() / ".aider" / "skills",
    ]
    extra = os.environ.get("AIDER_SKILLS_PATH", "")
    roots += [Path(p) for p in extra.split(os.pathsep) if p.strip()]
    return roots


class SkillTool(Tool):
    name = "Skill"
    description = (
        "Bir beceriyi yükler: o beceriye ait talimatlar bağlama eklenir ve sen onları "
        "izleyerek devam edersin. Eldeki iş mevcut becerilerden birinin kapsamına "
        "giriyorsa, kendi yaklaşımını uydurmadan ÖNCE beceriyi yükle."
    )
    parameters = {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "Beceri listesindeki tam ad"},
            "args": {
                "type": "string",
                "description": "Beceriye iletilecek isteğe bağlı argümanlar",
            },
        },
        "required": ["skill"],
    }

    def run(self, ctx, skill, args=None):
        lib = ctx.skills
        if not lib or not lib.skills:
            raise ToolError("bu projede tanımlı beceri yok")

        found = lib.get(skill)
        if not found:
            available = ", ".join(lib.skills) or "(yok)"
            raise ToolError(f"'{skill}' diye bir beceri yok. Mevcut: {available}")

        ctx.io.tool_output(f"Beceri yüklendi: {found.name}")
        out = found.render()
        if args:
            out += f"\n\n---\nBeceriye verilen argümanlar: {args}"

        # Büyük bir metin bağlama girdikten sonra zayıf modeller asıl görevi
        # kaybedip "hazırım, ne yapayım" diye soruyor. Ölçüldü: gemma4:e4b
        # beceriyi yükledikten sonra tam olarak bunu yapıyordu.
        out += (
            "\n\n---\n"
            "Yukarıdakiler talimattır, görev değildir. Şimdi kullanıcının son "
            "mesajındaki işi bu talimatları izleyerek YAP. Ne yapacağını sorma."
        )
        return out
