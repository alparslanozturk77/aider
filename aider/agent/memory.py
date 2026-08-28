"""Kalıcı bellek ve proje talimatları.

İki ayrı mekanizma:

**Proje talimatları** — depo kökündeki `AGENTS.md` / `KURALLAR.md` gibi bir
dosya her oturumda sistem promptuna eklenir. Claude Code'un `CLAUDE.md`
davranışının karşılığı. İnsan yazar, model okur.

**Bellek** — modelin ve kullanıcının biriktirdiği kısa notlar. Her not tek bir
dosya, tek bir olgu. Proje hedefleri, kullanıcının çalışma tercihleri, ortama
dair kolay unutulan gerçekler.

Bellek dizinleri, öncelik sırasıyla (beceri sistemiyle aynı desen):

    ~/.aider/memory/            kişisel, tüm projelerde
    <proje>/aider-memory/       proje, depoya girer, takımla paylaşılır
    <proje>/.aider/memory/      proje, kişisel, depoya girmez
"""

import os
import re
import unicodedata
from datetime import date
from pathlib import Path

from .registry import ToolError
from .skills import _parse_frontmatter
from .tools import Tool, _truncate

# Depo kökünde aranan talimat dosyaları, öncelik sırasıyla. İlk bulunan
# kullanılır; birden fazlası varsa hepsi eklenir.
INSTRUCTION_FILES = ("AGENTS.md", "KURALLAR.md", "CLAUDE.md", "CONVENTIONS.md")

# Bu boyutun üzerindeki talimat dosyaları küçük modelleri boğuyor: model
# talimatı "cevaplanacak içerik" sanıp özetliyor ve kullanıcının asıl isteğini
# görmezden geliyor. Ölçüldü (gemma4:e4b): 3 satırlık talimatla araç çağırıyor,
# 194 satırlıkla yalnızca özet üretiyor. Güçlü modellerde sorun değil, o yüzden
# kırpmıyoruz — yalnızca uyarıyoruz.
INSTRUCTION_WARN_CHARS = 4000

SHARED_MEMORY_DIR = "aider-memory"

# Bellek notlarının tamamı sistem promptuna giriyor. Notlar kısa olmak zorunda;
# bu sınır aşılırsa en yeniler tutulur ve kullanıcı uyarılır.
MEMORY_BUDGET = 12_000

# Not türleri. Model hangi tür olduğunu seçer; tür yalnızca okunabilirlik için.
TYPES = ("proje", "tercih", "ortam", "referans")


def _slug(text, limit=48):
    """Başlıktan dosya adı üret. Türkçe karakterleri ASCII'ye indirger."""
    text = text.strip().lower()
    for src, dst in (("ı", "i"), ("ğ", "g"), ("ü", "u"), ("ş", "s"), ("ö", "o"), ("ç", "c")):
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:limit].rstrip("-")) or "not"


class Memory:
    def __init__(self, name, tur, body, path, tarih=None):
        self.name = name
        self.tur = tur
        self.body = body
        self.path = path
        self.tarih = tarih

    def render(self):
        bas = f"- [{self.tur}] {self.name}"
        if self.tarih:
            bas += f" ({self.tarih})"
        return f"{bas}\n  {self.body.strip()}"


class MemoryStore:
    """Bellek notlarını diskten okur, yazar ve siler."""

    def __init__(self, roots):
        self.roots = [Path(r) for r in roots]
        self.notes = {}
        self.load()

    def load(self):
        self.notes = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.md")):
                if path.name.upper() == "INDEX.MD":
                    continue
                note = self._read(path)
                # Önce gelen kök kazanır: kişisel not paylaşılanı ezer.
                if note and note.name not in self.notes:
                    self.notes[note.name] = note
        return self.notes

    def _read(self, path):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        meta, body = _parse_frontmatter(text)
        if not body.strip():
            return None
        return Memory(
            name=meta.get("name") or path.stem,
            tur=meta.get("tur") or meta.get("type") or "proje",
            body=body,
            path=path,
            tarih=meta.get("tarih") or meta.get("date"),
        )

    def write(self, baslik, govde, tur="proje", root=None):
        """Notu diske yaz. Aynı adlı not varsa üzerine yazar."""
        if not baslik or not baslik.strip():
            raise ToolError("başlık boş olamaz")
        if not govde or not govde.strip():
            raise ToolError("not gövdesi boş olamaz")
        if tur not in TYPES:
            raise ToolError(f"geçersiz tür: {tur}. Geçerli: {', '.join(TYPES)}")

        root = Path(root) if root else self.roots[0]
        root.mkdir(parents=True, exist_ok=True)

        name = baslik.strip()
        path = root / f"{_slug(name)}.md"
        path.write_text(
            f"---\nname: {name}\ntur: {tur}\ntarih: {date.today().isoformat()}\n---\n\n"
            f"{govde.strip()}\n",
            encoding="utf-8",
        )
        self.load()
        return path

    def delete(self, name):
        note = self.notes.get(name)
        if not note:
            return None
        try:
            note.path.unlink()
        except OSError as err:
            raise ToolError(f"{note.path} silinemedi: {err}")
        self.load()
        return note.path

    def render(self):
        """Sistem promptuna eklenecek metin."""
        if not self.notes:
            return ""
        # Bütçe aşılırsa en yeni notlar tutulur; eskiler düşer.
        siralı = sorted(self.notes.values(), key=lambda n: (n.tarih or "", n.name), reverse=True)
        parcalar, toplam = [], 0
        for note in siralı:
            metin = note.render()
            if toplam + len(metin) > MEMORY_BUDGET:
                break
            parcalar.append(metin)
            toplam += len(metin)
        return "\n".join(parcalar)

    def dropped(self):
        """Bütçe yüzünden prompta girmeyen not sayısı."""
        rendered = self.render()
        return sum(1 for n in self.notes.values() if n.render() not in rendered)


def default_memory_roots(project_root):
    project_root = Path(project_root)
    roots = [
        project_root / ".aider" / "memory",
        project_root / SHARED_MEMORY_DIR,
        Path.home() / ".aider" / "memory",
    ]
    extra = os.environ.get("AIDER_MEMORY_PATH", "")
    roots += [Path(p) for p in extra.split(os.pathsep) if p.strip()]
    return roots


def load_instructions(project_root):
    """Depo kökündeki talimat dosyalarını oku.

    (metin, bulunan_dosyalar) döndürür.
    """
    root = Path(project_root)
    parcalar, bulunan = [], []
    for name in INSTRUCTION_FILES:
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        parcalar.append(f"### {name}\n\n{text}")
        bulunan.append(path)
    return _truncate("\n\n".join(parcalar), 20_000), bulunan


class HatirlaTool(Tool):
    name = "Hatirla"
    description = (
        "Sonraki oturumlarda da geçerli olacak kalıcı bir not kaydeder. Kullanıcı "
        "bir tercihini, projenin hedefini ya da ortama dair kolay unutulan bir "
        "gerçeği söylediğinde kullan. Yalnızca gelecekte işe yarayacak, kalıcı "
        "bilgiyi kaydet — bu oturuma özgü ayrıntıları değil. Kod tabanından "
        "okunabilecek şeyleri (dosya yapısı, fonksiyon adları) kaydetme."
    )
    mutating = True
    parameters = {
        "type": "object",
        "properties": {
            "baslik": {
                "type": "string",
                "description": "Kısa başlık; dosya adı bundan üretilir",
            },
            "not": {
                "type": "string",
                "description": "Notun kendisi. Tek bir olgu. Nedenini de yaz.",
            },
            "tur": {
                "type": "string",
                "enum": list(TYPES),
                "description": (
                    "proje: hedef ve kısıtlar | tercih: kullanıcının çalışma şekli | "
                    "ortam: altyapıya dair gerçekler | referans: dış kaynak"
                ),
            },
        },
        "required": ["baslik", "not"],
    }

    def run(self, ctx, baslik, **kwargs):
        govde = kwargs.get("not") or kwargs.get("note") or ""
        tur = kwargs.get("tur", "proje")

        if not ctx.confirm(
            self.name, f"[{tur}] {baslik}\n  {govde[:200]}", "Bu notu kalıcı olarak kaydet?"
        ):
            return "Kullanıcı bu notu kaydetmeyi reddetti."

        path = ctx.memory.write(baslik, govde, tur)
        ctx.io.tool_output(f"Not kaydedildi: {path}")
        return f"Kaydedildi: {path}. Sonraki oturumlarda bu not otomatik yüklenecek."
