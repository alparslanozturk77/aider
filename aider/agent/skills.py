"""SKILL.md tabanlı beceri sistemi.

Claude Code'daki gibi: her beceri bir klasör, içinde YAML frontmatter'lı bir
SKILL.md. Sistem promptuna yalnızca ad + açıklama enjekte edilir (ucuz); gövde
ancak model beceriyi Skill aracıyla çağırınca yüklenir (progressive disclosure).

Aranan yerler, öncelik sırasıyla:
  1. <proje>/.aider/skills/   kişisel, .gitignore'daki .aider* ile depo dışında
  2. <proje>/aider-skills/    takımla paylaşılan, depoya girer
  3. ~/.aider/skills/         tüm projelerde geçerli kişisel beceriler
  4. AIDER_SKILLS_PATH ortam değişkenindeki iki nokta ile ayrılmış dizinler
  5. aider/beceriler/         programla birlikte gelen yerleşik beceriler

Sıra bilinçli: aynı adlı bir beceri birden çok dizinde varsa önce gelen
kazanır. Kişisel beceri paylaşılanı, paylaşılan da yerleşiği ezer; yani
programla gelen bir beceriyi kendi kopyanla değiştirebilirsin.

Yerleşik beceriler en sonda ve paketin İÇİNDE duruyor. Sebep ölçüldü:
depo `/root/aider`'a klonlanıp `/root/aider-work` içinde çalışılınca beceri
dizinlerinin hiçbiri eşleşmiyor ve program "0 beceri yüklendi" diyor. Beceri
dosyaları programla birlikte taşınırsa hangi dizinde çalışıldığının önemi
kalmıyor.
"""

import os
import re
from pathlib import Path

from .registry import ToolError
from .tools import MAX_OUTPUT_CHARS, Tool, _truncate

SKILL_FILE = "SKILL.md"
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

# Açıklamalardaki tırnak içi tetikleyici kelimeler. Otuz yedi becerinin
# hepsi zaten bu biçimde yazılmış ("ansible", "playbook", ...), o yüzden
# ayrı bir alan doldurmak gerekmiyor; frontmatter'daki `triggers:` yalnızca
# bunu ezmek isteyen beceriler için.
_TIRNAK = re.compile(r'["“”]([^"“”\n]{2,60})["“”]')

# Türkçe harfleri ASCII'ye indirger. İki yönlü fayda: "bağlanamıyor" ile
# "baglanamiyor" aynı kelimeye iner, yani kullanıcı Türkçe karakter
# kullanmadan yazsa da eşleşme tutar.
_TR = str.maketrans(
    {
        "ı": "i", "İ": "i", "I": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u",
        "ş": "s", "Ş": "s", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c", "â": "a", "î": "i",
    }
)

# Bundan kısa tetikleyiciler eşleştirmede kullanılmaz: iki harflik bir dizge
# rastgele kelimelerin içine düşüyor.
MIN_TETIKLEYICI = 3


def normalize(text):
    return (text or "").translate(_TR).lower()


def _tetikleyici_regex(ifade):
    """Kelime başına demirleyen desen.

    Sağ sınır YOK: Türkçe ekler kelimeye bitişik yazılıyor ve "playbook'u",
    "ansible'da" gibi biçimlerin eşleşmesi gerekiyor. Sol sınır ise şart,
    yoksa tetikleyici rastgele kelimelerin ortasına düşüyor.
    """
    return re.compile(r"(?<![a-z0-9])" + re.escape(ifade))


def _tirnaklari_soy(val):
    """Yalnızca değerin TAMAMI tırnak içindeyse tırnakları kaldır.

    İki uçtan ayrım gözetmeden kırpmak, tırnaklı bir tetikleyiciyle biten
    açıklamanın son tetikleyicisini bozuyordu:
    `... "pip", "paket"` -> `... "pip", "paket` ve o tetikleyici artık
    eşleşmiyor.
    """
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
        return val[1:-1]
    return val


def _parse_frontmatter(text):
    """Minimal YAML frontmatter ayrıştırıcı (name/description düzeyinde).

    PyYAML'a bağımlılık eklememek için kasıtlı olarak basit tutuldu; beceri
    frontmatter'ı düz `anahtar: değer` çiftlerinden oluşur.

    Girintili satırlar önceki değerin devamı sayılır (YAML katlanmış dizge).
    Bu şart: uzun bir `description` iki satıra yayıldığında ikinci satır
    sessizce düşüyordu ve o satırdaki tetikleyici kelimeler kayboluyordu —
    `/beceri-uret`'in ürettiği iskeletin açıklaması tam olarak böyle.

    Sınır: iç içe eşleme (nested mapping) desteklenmiyor; girintili bir
    `anahtar: değer` satırı üstteki değerin devamı olarak katlanır.
    """
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text

    meta = {}
    son_anahtar = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue

        if son_anahtar and line[:1].isspace():
            meta[son_anahtar] = (meta[son_anahtar] + " " + line.strip()).strip()
            continue

        if ":" not in line:
            continue

        key, _, val = line.partition(":")
        son_anahtar = key.strip()
        meta[son_anahtar] = _tirnaklari_soy(val.strip())
    return meta, m.group(2)


class Skill:
    def __init__(self, name, description, path, body, triggers=None, auto=True):
        self.name = name
        self.description = description
        self.path = path
        self.body = body
        self.auto = auto
        # (ham ifade, derlenmiş desen) çiftleri
        self.triggers = triggers or []

    def render(self, limit=MAX_OUTPUT_CHARS):
        """Modele verilecek tam beceri metni."""
        header = f"# Beceri: {self.name}\n\nKaynak: {self.path}\n"
        return _truncate(f"{header}\n{self.body.strip()}", limit)

    def eslesen_tetikleyiciler(self, normalize_metin):
        return [ham for ham, desen in self.triggers if desen.search(normalize_metin)]


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
        return Skill(
            name,
            desc,
            path,
            body,
            triggers=_tetikleyicileri_cikar(meta, desc, name),
            auto=str(meta.get("auto", "true")).strip().lower() not in ("false", "hayir", "hayır"),
        )

    def catalog(self):
        """Sistem promptuna gömülecek kısa liste."""
        if not self.skills:
            return ""
        lines = [f"- {s.name}: {s.description}" for s in self.skills.values()]
        return "\n".join(lines)

    def get(self, name):
        return self.skills.get(name)

    def eslestir(self, metin, limit=1):
        """Kullanıcı mesajına uyan becerileri en iyiden başlayarak döndür.

        Modelin karar vermesini beklemiyoruz. Ölçüldü: 14 beceri yüklüyken
        gemma4:e4b "OS güncel mi" isteğinde Skill aracını bir kez bile
        çağırmadı. Katalog sistem promptunda duruyor ama 4B sınıfı bir model
        onlarca satırdan doğru olanı seçip araç çağırmayı beceremiyor.

        [(beceri, eşleşen tetikleyiciler)] döndürür.
        """
        norm = normalize(metin)
        if not norm.strip():
            return []

        skorlar = []
        for skill in self.skills.values():
            if not skill.auto:
                continue
            vurus = skill.eslesen_tetikleyiciler(norm)
            if vurus:
                # Eşitlik bozucu: az tetikleyicili beceri daha uzmandır.
                # "hammer" hem rhel-yonetim'de hem satellite-yonetim'de var;
                # ikincisi daha az konu iddia ettiği için o kazanmalı.
                skorlar.append((self._puan(skill, vurus), -len(skill.triggers), skill, vurus))

        skorlar.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [(s[2], s[3]) for s in skorlar[:limit]]

    @staticmethod
    def _puan(skill, vurus):
        """Eşleşmenin isabet puanı.

        Becerinin kendi adının geçmesi en güçlü sinyal: kullanıcı "ansible ile
        ... kontrol et" dediğinde aracı adıyla anmıştır. Ad ağırlığı olmadan
        genel bir ifade ("kontrol et", 10 karakter) becerinin adını
        ("ansible", 7 karakter) geçiyordu ve yanlış beceri yükleniyordu.
        """
        ad = normalize(skill.name)
        puan = 10 * len(vurus) + max(len(v) for v in vurus)
        if ad in vurus:
            puan += 50
        return puan


def _tetikleyicileri_cikar(meta, description, name):
    """Frontmatter'daki `triggers:` yoksa açıklamadaki tırnaklı ifadelerden üret."""
    ham = meta.get("triggers") or meta.get("tetikleyiciler")
    if ham:
        ifadeler = [p.strip() for p in ham.split(",")]
    else:
        ifadeler = _TIRNAK.findall(description)

    # Becerinin kendi adı da tetikleyici: kullanıcı "selinux" ya da "ansible"
    # yazdığında o beceriyi kastediyordur.
    ifadeler.append(name)

    cikti, gorulen = [], set()
    for ifade in ifadeler:
        norm = normalize(ifade).strip()
        if len(norm) < MIN_TETIKLEYICI or norm in gorulen:
            continue
        gorulen.add(norm)
        cikti.append((norm, _tetikleyici_regex(norm)))
    return cikti


# Depoya girebilen, paylaşılan beceri dizini. Gizli dizin değil, çünkü
# .gitignore'daki .aider* kuralı .aider/skills/ altını depo dışında bırakıyor.
SHARED_SKILLS_DIR = "aider-skills"

# Programla birlikte gelen beceriler. Paketin içinde durduğu için wheel'e,
# çevrimdışı pakete ve RPM'e kendiliğinden giriyor; kurulumda ayrıca
# kopyalanması ya da sembolik bağ kurulması gerekmiyor.
YERLESIK_BECERILER = Path(__file__).resolve().parent.parent / "beceriler"


def default_skill_roots(project_root):
    project_root = Path(project_root)
    roots = [
        project_root / ".aider" / "skills",
        project_root / SHARED_SKILLS_DIR,
        Path.home() / ".aider" / "skills",
    ]
    extra = os.environ.get("AIDER_SKILLS_PATH", "")
    roots += [Path(p) for p in extra.split(os.pathsep) if p.strip()]
    # En sonda: yerleşik beceriler aynı adlı yerel bir beceriyi ezmesin.
    roots.append(YERLESIK_BECERILER)
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
