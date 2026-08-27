import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from aider.agent.plan import ExitPlanModeTool
from aider.agent.registry import ToolContext, ToolError, ToolRegistry
from aider.agent.skills import SkillLibrary, SkillTool, _parse_frontmatter
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

    def test_adds_file_to_chat_context(self):
        p = self.root / "a.txt"
        p.write_text("x")
        ReadTool().run(self.ctx, file_path="a.txt")
        self.assertIn(str(p.resolve()), self.ctx.coder.abs_fnames)


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
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n"
        )

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
                    tool_calls=[
                        FakeToolCall("c1", "Read", json.dumps({"file_path": "veri.txt"}))
                    ]
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
