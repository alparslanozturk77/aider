#!/usr/bin/env python3
"""Fork değişmezlerini doğrular.

Upstream aider'dan `git merge` yaptıktan sonra çalıştır. Fork'un upstream
dosyalarına yaptığı dokunuşların hâlâ yerinde ve ÇALIŞIR durumda olduğunu
kontrol eder.

Kontroller kasıtlı olarak davranışsaldır: dosyada metin aramak yerine kodu
gerçekten çağırır. Bir merge yaman satırları koruyup davranışı bozabilir;
metin araması bunu kaçırır.

Kullanım:
    python scripts/fork_dogrula.py            # tüm kontroller
    python scripts/fork_dogrula.py --liste    # kontrolleri listele

Çıkış kodu 0 ise fork sağlam, 1 ise en az bir değişmez bozulmuş.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Her kontrol: (ad, dokunulan upstream dosyası, açıklama, fonksiyon)
CHECKS = []


def check(name, upstream_file, why):
    def deco(fn):
        CHECKS.append((name, upstream_file, why, fn))
        return fn

    return deco


class Fail(Exception):
    """Değişmez bozulmuş."""


# ---------------------------------------------------------------------------
# aider/models.py
# ---------------------------------------------------------------------------


@check(
    "tool_choice=auto",
    "aider/models.py",
    "Agentic döngü modelin araçlar arasından KENDİSİ seçmesini gerektirir. "
    "Upstream send_completion tool_choice'u tek bir fonksiyona zorluyor.",
)
def _check_tool_choice_auto():
    from unittest.mock import MagicMock, patch

    from aider.models import Model

    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    tools = [
        dict(type="function", function=dict(name="Read", description="d", parameters={})),
        dict(type="function", function=dict(name="Bash", description="d", parameters={})),
    ]
    with patch("litellm.completion", side_effect=fake):
        Model("gpt-4o").send_completion([{"role": "user", "content": "x"}], tools, False)

    if captured.get("tool_choice") != "auto":
        raise Fail(f"tool_choice 'auto' olmalıydı, gelen: {captured.get('tool_choice')!r}")
    if len(captured.get("tools", [])) != 2:
        raise Fail(f"iki araç geçirilmeliydi, gelen: {len(captured.get('tools', []))}")


@check(
    "eski tool biçimi korunuyor",
    "aider/models.py",
    "Yamamız upstream'in tek-fonksiyon davranışını bozmamalı; "
    "wholefile_func gibi coder'lar ona bağlı.",
)
def _check_legacy_tool_format():
    from unittest.mock import MagicMock, patch

    from aider.models import Model

    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    with patch("litellm.completion", side_effect=fake):
        Model("gpt-4o").send_completion(
            [{"role": "user", "content": "x"}],
            [dict(name="write_file", description="d", parameters={})],
            False,
        )

    choice = captured.get("tool_choice")
    if not isinstance(choice, dict) or choice.get("function", {}).get("name") != "write_file":
        raise Fail(f"tek fonksiyona zorlama kaybolmuş, gelen tool_choice: {choice!r}")


# ---------------------------------------------------------------------------
# aider/coders/__init__.py
# ---------------------------------------------------------------------------


@check(
    "AgentCoder kayıtlı",
    "aider/coders/__init__.py",
    "Coder.create edit_format='agent' isteğini bu kayıt üzerinden çözer.",
)
def _check_agent_coder_registered():
    from aider import coders

    formats = {
        c.edit_format
        for c in coders.__all__
        if hasattr(c, "edit_format") and c.edit_format is not None
    }
    if "agent" not in formats:
        raise Fail(f"'agent' edit_format kayıtlı değil. Kayıtlılar: {sorted(formats)}")


# ---------------------------------------------------------------------------
# aider/args.py
# ---------------------------------------------------------------------------


@check(
    "CLI bayrakları",
    "aider/args.py",
    "Agent modu ve izin sistemi bu bayraklarla sürülüyor.",
)
def _check_cli_flags():
    from aider.args import get_parser

    parser = get_parser([], None)
    known = set()
    for action in parser._actions:
        known.update(action.option_strings)

    required = [
        "--agent",
        "--plan",
        "--auto",
        "--permission-mode",
        "--max-tool-iterations",
        "--offline",
    ]
    missing = [f for f in required if f not in known]
    if missing:
        raise Fail(f"eksik bayraklar: {', '.join(missing)}")

    # --agent gerçekten edit_format'ı ayarlıyor mu?
    args = parser.parse_args(["--agent"])
    if args.edit_format != "agent":
        raise Fail(f"--agent edit_format'ı 'agent' yapmıyor, sonuç: {args.edit_format!r}")

    args = parser.parse_args(["--auto"])
    if args.permission_mode != "auto":
        raise Fail("--auto permission_mode'u 'auto' yapmıyor")

    # --offline gerçekten ağa çıkan davranışları kapatıyor mu? Bayrağın var
    # olması yetmez; hava boşluklu sunucuda önemli olan etkisi.
    from aider.main import cevrimdisi_uygula

    args = cevrimdisi_uygula(parser.parse_args(["--offline"]))
    acik = [
        ad
        for ad in ("check_update", "just_check_update", "analytics", "detect_urls")
        if getattr(args, ad) not in (False, None)
    ]
    if acik:
        raise Fail("--offline şunları kapatmıyor: " + ", ".join(acik))


# ---------------------------------------------------------------------------
# aider/main.py
# ---------------------------------------------------------------------------


@check(
    "agent kwarg aktarımı",
    "aider/main.py",
    "plan_mode / max_iterations / permission_mode yalnızca AgentCoder'a "
    "geçirilmeli; diğer coder'lar bu anahtarları kabul etmez.",
)
def _check_main_passes_agent_kwargs():
    src = (REPO / "aider" / "main.py").read_text(encoding="utf-8")
    if "agent_kwargs" not in src:
        raise Fail("main.py içinde agent_kwargs bloğu yok — merge sırasında düşmüş olabilir")
    if "**agent_kwargs," not in src:
        raise Fail("agent_kwargs Coder.create çağrısına geçirilmiyor")

    # Davranışsal doğrulama: agent olmayan bir coder bu kwarg'ları almamalı.
    from aider.coders import Coder
    from aider.io import InputOutput
    from aider.models import Model

    with tempfile.TemporaryDirectory() as tmp:
        io = InputOutput(yes=True, pretty=False, fancy_input=False)
        coder = Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=io,
            fnames=[],
            use_git=False,
            plan_mode=True,
            max_iterations=7,
            permission_mode="auto",
        )
        if coder.max_iterations != 7:
            raise Fail("max_iterations AgentCoder'a ulaşmıyor")
        if not coder.plan_mode:
            raise Fail("plan_mode AgentCoder'a ulaşmıyor")
        _ = tmp


# ---------------------------------------------------------------------------
# .gitignore
# ---------------------------------------------------------------------------


@check(
    ".gitignore dengesi",
    ".gitignore",
    "Şablonlar ve paylaşılan beceriler depoda kalmalı; .env ve .mcp.json "
    "gizli bilgi taşıdığı için kalmamalı. Aider .gitignore sonuna .aider* "
    "ekleyebiliyor, bu denge sessizce bozulabiliyor.",
)
def _check_gitignore():
    import subprocess

    def ignored(path):
        # --no-index şart: git check-ignore izlenen dosyaları varsayılan olarak
        # atlar ve desen eşleşse bile "ignore edilmiyor" der. O hâliyle bu
        # kontrol bozulmayı hiç yakalayamıyordu.
        r = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=REPO,
            capture_output=True,
        )
        return r.returncode == 0

    must_be_tracked = [
        "ornek/aider.conf.yml",
        "ornek/permissions.yml",
        "ornek/mcp.json",
        "aider/beceriler/kod-inceleme/SKILL.md",
    ]
    wrongly_ignored = [p for p in must_be_tracked if ignored(p)]
    if wrongly_ignored:
        raise Fail(
            "depoda kalması gereken dosyalar ignore edilmiş: "
            + ", ".join(wrongly_ignored)
            + " — .gitignore'a '!' negasyonu EKLEME, dosyaları .aider ile "
            "başlamayan bir dizine taşı"
        )

    must_be_ignored = [".env", ".mcp.json"]
    leaking = [p for p in must_be_ignored if not ignored(p)]
    if leaking:
        raise Fail(f"gizli bilgi taşıyan dosyalar ignore edilmiyor: {', '.join(leaking)}")


# ---------------------------------------------------------------------------
# aider/io.py
# ---------------------------------------------------------------------------


@check(
    "io kancaları",
    "aider/io.py",
    "Mod göstergesi prompt önekine bu kancayla giriyor ve shift+tab buna "
    "bağlı. Kanca düşerse mod görünmez olur, kullanıcı hangi modda olduğunu "
    "bilemez.",
)
def _check_io_hooks():
    import inspect

    from aider.io import InputOutput

    io = InputOutput(yes=True, pretty=False, fancy_input=False)
    for ad in ("agent_status", "agent_cycle_mode"):
        if not hasattr(io, ad):
            raise Fail(f"InputOutput.{ad} yok")
        if getattr(io, ad) is not None:
            raise Fail(f"{ad} varsayılan olarak None olmalı, diğer coder'ları etkilememeli")

    src = inspect.getsource(InputOutput.get_input)
    if "self.agent_status()" not in src:
        raise Fail("prompt öneki agent_status'u çağırmıyor — mod göstergesi kaybolmuş")
    if '@kb.add("s-tab")' not in src:
        raise Fail("shift+tab bağlaması yok")

    # Geri alınmış bir denemeydi; geri gelirse terminali bozar.
    if "bottom_toolbar=self.agent_status" in src:
        raise Fail(
            "bottom_toolbar geri gelmiş — terminali raw modda bırakıp merdiven "
            "etkisi yapıyor, bilinçli olarak kaldırılmıştı"
        )


@check(
    "agent kancaları bağlanıyor",
    "aider/coders/agent_coder.py",
    "AgentCoder kancaları doldurmazsa mod göstergesi hiç görünmez.",
)
def _check_hooks_installed():
    import tempfile

    from aider.coders import Coder
    from aider.io import InputOutput
    from aider.models import Model

    with tempfile.TemporaryDirectory() as tmp:
        onceki = os.getcwd()
        os.chdir(tmp)
        try:
            io = InputOutput(yes=True, pretty=False, fancy_input=False)
            coder = Coder.create(
                main_model=Model("gpt-4o"), edit_format="agent", io=io,
                fnames=[], use_git=False,
            )
            if not callable(io.agent_status):
                raise Fail("AgentCoder io.agent_status'u doldurmuyor")
            if not callable(io.agent_cycle_mode):
                raise Fail("AgentCoder io.agent_cycle_mode'u doldurmuyor")
            if not coder._status_text().strip():
                raise Fail("mod göstergesi boş dönüyor")

            # Diğer coder'lar etkilenmemeli.
            io2 = InputOutput(yes=True, pretty=False, fancy_input=False)
            Coder.create(
                main_model=Model("gpt-4o"), edit_format="diff", io=io2,
                fnames=[], use_git=False,
            )
            if io2.agent_status is not None:
                raise Fail("agent olmayan coder'da kanca doluyor — upstream davranışı bozulur")
        finally:
            os.chdir(onceki)


# ---------------------------------------------------------------------------
# aider/commands.py
# ---------------------------------------------------------------------------


@check(
    "slash komutları",
    "aider/commands.py",
    "Agent katmanının kullanıcı arayüzü bu komutlar. Bir merge Commands "
    "sınıfını yeniden düzenlerse sessizce düşebilirler.",
)
def _check_commands():
    from aider.commands import Commands

    gerekli = [
        "agent", "plan", "mod", "skills", "mcp", "permissions",
        "todo", "hatirla", "bellek", "unut", "model_ekle", "beceri_uret",
    ]
    eksik = [k for k in gerekli if not hasattr(Commands, f"cmd_{k}")]
    if eksik:
        raise Fail("eksik komutlar: " + ", ".join("/" + k.replace("_", "-") for k in eksik))


# ---------------------------------------------------------------------------
# Agent katmanının kendisi
# ---------------------------------------------------------------------------


@check(
    "araç seti eksiksiz",
    "aider/agent/",
    "Sistem promptu bu araçların varlığını varsayıyor.",
)
def _check_tools_present():
    from aider.agent.mcp import MCPManager  # noqa: F401
    from aider.agent.plan import ExitPlanModeTool
    from aider.agent.registry import ToolRegistry
    from aider.agent.skills import SkillTool
    from aider.agent.todo import TodoWriteTool
    from aider.agent.tools import (
        BashTool,
        EditTool,
        GlobTool,
        GrepTool,
        ReadTool,
        WriteTool,
    )

    reg = ToolRegistry(
        [
            ReadTool(), WriteTool(), EditTool(), BashTool(), GlobTool(),
            GrepTool(), TodoWriteTool(), SkillTool(), ExitPlanModeTool(),
        ]
    )
    expected = {
        "Read", "Write", "Edit", "Bash", "Glob", "Grep",
        "TodoWrite", "Skill", "ExitPlanMode",
    }
    missing = expected - set(reg.names())
    if missing:
        raise Fail(f"eksik araçlar: {', '.join(sorted(missing))}")

    # Şemalar OpenAI biçiminde olmalı, yoksa model araçları göremez.
    for schema in reg.schemas():
        fn = schema.get("function", {})
        if schema.get("type") != "function" or not fn.get("name") or not fn.get("description"):
            raise Fail(f"bozuk araç şeması: {json.dumps(schema)[:200]}")


@check(
    "izin kaçışları kapalı",
    "aider/agent/permissions.py",
    "İzin sistemi bir güvenlik sınırı. Bu üç kaçış yolu açılırsa bir izin "
    "kuralı yetkisiz komut geçirir.",
)
def _check_permission_escapes():
    from aider.agent.permissions import ALLOW, ASK, DENY, PermissionSet

    p = PermissionSet(allow=["Bash(git diff:*)"], mode="ask")

    escapes = {
        "zincirleme": "git diff && npm publish",
        "komut ikamesi": "git diff $(rm -rf /tmp/x)",
        "backtick ikamesi": "git diff `whoami`",
        "sözcük sınırı": "git diff-tree HEAD",
    }
    for adi, cmd in escapes.items():
        if p.decide("Bash", {"command": cmd}, True) == ALLOW:
            raise Fail(f"{adi} kaçışı AÇIK: {cmd!r} otomatik onaylandı")

    # Uzak kabuk yerel yasakları atlamamalı: Bash(rm -rf /*) reddi Ssh ile
    # gönderilen komutu da kapsamalı, yoksa yasak sunucularda anlamsız kalır.
    auto = PermissionSet(mode="auto")
    for cmd in ("rm -rf /", "sudo reboot", "mkfs.ext4 /dev/sdb", "uptime && sudo reboot"):
        if auto.decide("Ssh", {"host": "s", "command": cmd}, True) == ALLOW:
            raise Fail(f"Ssh yerel reddi atlıyor: {cmd!r} oto modda onaylandı")

    # Üç katman: yıkıcı olan asla, orta katman oto modda bile sorulur ama
    # kullanıcının açık izniyle çalışır.
    if auto.decide("Bash", {"command": "reboot"}, True) != ASK:
        raise Fail("reboot oto modda sorulmuyor — orta katman kayıp")
    if PermissionSet(mode="auto", allow=["Bash(reboot:*)"]).decide(
        "Bash", {"command": "reboot"}, True
    ) != ALLOW:
        raise Fail("kullanıcının açık reboot izni işlemiyor")
    if PermissionSet(mode="auto", allow=["Bash(rm -rf /*)"]).decide(
        "Bash", {"command": "rm -rf /"}, True
    ) != DENY:
        raise Fail("yıkıcı komut kullanıcı izniyle açılabiliyor")

    # Yerleşik reddetme listesi auto modda da geçerli olmalı.
    for cmd in ["rm -rf /", "mkfs.ext4 /dev/sda", "dd if=/dev/zero of=/dev/sda"]:
        if auto.decide("Bash", {"command": cmd}, True) != DENY:
            raise Fail(f"yerleşik deny listesi {cmd!r} komutunu engellemiyor")

    # Orta katman auto modda otomatik onaylanmamalı.
    for cmd in ["sudo rm x", "git push", "reboot", "shutdown -h now"]:
        if auto.decide("Bash", {"command": cmd}, True) == ALLOW:
            raise Fail(f"{cmd!r} oto modda sorulmadan onaylandı")


@check(
    "beceri keşfi",
    "aider/agent/skills.py",
    "Beceriler hem kişisel hem paylaşılan dizinden okunmalı.",
)
def _check_skill_discovery():
    import tempfile

    from aider.agent.skills import (
        SHARED_SKILLS_DIR,
        YERLESIK_BECERILER,
        SkillLibrary,
        default_skill_roots,
    )

    roots = [str(r) for r in default_skill_roots(REPO)]
    if not any(r.endswith(SHARED_SKILLS_DIR) for r in roots):
        raise Fail(f"paylaşılan beceri dizini ({SHARED_SKILLS_DIR}) arama yollarında yok")

    lib = SkillLibrary(default_skill_roots(REPO))
    if not lib.skills:
        raise Fail(f"depodaki örnek beceriler bulunamadı. Aranan: {roots}")

    # Asıl değişmez: beceriler depo dışında bir dizinde de görünmeli. Ölçülen
    # arıza — depo /root/aider'a klonlanıp /root/aider-work içinde çalışılınca
    # "Beceriler: 0 yüklendi" oluyordu.
    with tempfile.TemporaryDirectory() as baska_dizin:
        disarda = SkillLibrary(default_skill_roots(baska_dizin))
        if len(disarda.skills) < len(lib.skills):
            raise Fail(
                "beceriler depo dışında bir dizinde görünmüyor: "
                f"depoda {len(lib.skills)}, dışarıda {len(disarda.skills)}. "
                "Yerleşik beceriler paketin içinde mi?"
            )
    for skill in lib.skills.values():
        if not skill.description:
            raise Fail(f"'{skill.name}' becerisinin description'ı yok — model onu tetikleyemez")

    # Beceriler birbirine "`ad` becerisine geç" diye yönlendiriyor. Hedef
    # yoksa model boşluğa gönderilir ve bu sessizce olur; bir beceriyi
    # yeniden adlandırmak ya da bölmek bu bağı kolayca koparıyor.
    import re

    adlar = set(lib.skills)
    kirik = set()
    beceri_dosyalari = sorted(YERLESIK_BECERILER.glob("*/SKILL.md"))
    if not beceri_dosyalari:
        raise Fail(f"yerleşik beceri dizini boş ya da yok: {YERLESIK_BECERILER}")
    for yol in beceri_dosyalari:
        metin = yol.read_text(encoding="utf-8")
        # Kanonik biçim: "`ad` becerisi/becerisine/becerisini". Yalnızca bunu
        # arıyoruz; serbest metinde geçen komut adları yanlış alarm veriyor.
        for m in re.finditer(r"`([a-z0-9-]+)` becerisi", metin):
            if m.group(1) not in adlar:
                kirik.add(f"{yol.parent.name} -> {m.group(1)}")
    if kirik:
        raise Fail("var olmayan beceriye yönlendirme: " + ", ".join(sorted(kirik)))


@check(
    "README fork'un",
    "README.md",
    "Depo ön yüzü fork'u anlatmalı. Merge upstream README'sini geri getirirse "
    "GitHub'da aider'ın kendi sayfası görünür ve fork'un ne olduğu kaybolur.",
)
def _check_readme():
    readme = REPO / "README.md"
    if not readme.is_file():
        raise Fail("README.md yok")
    metin = readme.read_text(encoding="utf-8")
    if "aider-agent" not in metin.splitlines()[0]:
        raise Fail(
            "README.md fork'un değil — ilk satırda 'aider-agent' yok. "
            "Merge upstream sürümünü geri getirmiş olabilir."
        )
    if not (REPO / "ORIJINAL-README.md").is_file():
        raise Fail("ORIJINAL-README.md yok — upstream README'si korunmalı")


def main():
    ap = argparse.ArgumentParser(description="Fork değişmezlerini doğrula")
    ap.add_argument("--liste", action="store_true", help="kontrolleri listele ve çık")
    args = ap.parse_args()

    if args.liste:
        for name, f, why, _ in CHECKS:
            print(f"{name:28} {f}")
            print(f"{'':28} {why}\n")
        return 0

    print(f"Fork değişmezleri kontrol ediliyor ({len(CHECKS)} kontrol)\n")

    failures = []
    for name, upstream_file, why, fn in CHECKS:
        try:
            fn()
        except Fail as err:
            failures.append((name, upstream_file, why, str(err)))
            print(f"  BOZUK   {name}")
        except Exception as err:
            failures.append((name, upstream_file, why, f"{err.__class__.__name__}: {err}"))
            print(f"  HATA    {name}")
        else:
            print(f"  tamam   {name}")

    if not failures:
        print("\nTüm değişmezler yerinde. Şimdi testleri çalıştır:")
        print("  .venv/bin/python -m pytest tests/basic -q")
        return 0

    print(f"\n{len(failures)} değişmez bozulmuş:\n")
    for name, upstream_file, why, err in failures:
        print(f"--- {name}  ({upstream_file}) ---")
        print(f"  Sorun : {err}")
        print(f"  Neden : {why}")
        print(f"  Bak   : git diff <merge-oncesi>..HEAD -- {upstream_file}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
