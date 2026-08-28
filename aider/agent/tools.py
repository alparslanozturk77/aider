"""Claude Code tarzı araç seti: Read, Write, Edit, Bash, Grep, Glob, TodoWrite...

Her araç bir OpenAI function-calling şeması ve bir `run()` metodu sunar.
Sonuçlar daima modele geri beslenebilir düz metindir.
"""

import fnmatch
import os
import subprocess
from pathlib import Path

from .registry import ToolError

# Araç çıktısının modele verilmeden önce kırpılacağı sınır. Bağlam penceresini
# tek bir devasa dosya/komut çıktısının yutmasını engeller.
MAX_OUTPUT_CHARS = 30_000
DEFAULT_READ_LIMIT = 2000

# Grep/Glob taramalarında hiçbir zaman girilmeyecek dizinler.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".aider.tags.cache.v4",
    ".tox",
    ".next",
    "target",
}


def _truncate(text, limit=MAX_OUTPUT_CHARS):
    if len(text) <= limit:
        return text
    kept = text[:limit]
    dropped = len(text) - limit
    return f"{kept}\n\n... [çıktı kırpıldı, {dropped} karakter atlandı]"


class Tool:
    name = None
    description = ""
    parameters = {"type": "object", "properties": {}}
    # Yan etkili araçlar kullanıcı onayı ister; plan modunda tamamen bloklanır.
    mutating = False

    def run(self, ctx, **kwargs):
        raise NotImplementedError


class PathTool(Tool):
    """Yol çözümlemesini paylaşan araçlar için ortak taban."""

    def resolve(self, ctx, file_path):
        if not file_path:
            raise ToolError("file_path zorunlu")
        p = Path(file_path).expanduser()
        if not p.is_absolute():
            p = Path(ctx.root) / p
        return p


class ReadTool(PathTool):
    name = "Read"
    description = (
        "Diskten bir dosya okur ve satır numaralı olarak döndürür. Büyük dosyalarda "
        "offset/limit ile parça parça okuyabilirsin. Bir dosyayı düzenlemeden önce "
        "MUTLAKA oku."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Okunacak dosyanın yolu (mutlak ya da proje köküne göreli)",
            },
            "offset": {
                "type": "integer",
                "description": "Kaçıncı satırdan başlanacağı (1 tabanlı)",
            },
            "limit": {
                "type": "integer",
                "description": f"Okunacak satır sayısı (varsayılan {DEFAULT_READ_LIMIT})",
            },
        },
        "required": ["file_path"],
    }

    def run(self, ctx, file_path, offset=None, limit=None):
        p = self.resolve(ctx, file_path)
        if not p.exists():
            raise ToolError(f"{p} yok")
        if p.is_dir():
            raise ToolError(f"{p} bir dizin, dosya değil. Listelemek için Glob kullan.")

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            raise ToolError(f"{p} okunamadı: {err}")

        if not text.strip():
            return f"(dosya boş: {p})"

        lines = text.splitlines()
        start = max(1, offset or 1)
        count = limit or DEFAULT_READ_LIMIT
        chunk = lines[start - 1 : start - 1 + count]

        if not chunk:
            return f"(offset {start}, dosyada yalnızca {len(lines)} satır var)"

        width = len(str(start + len(chunk) - 1))
        body = "\n".join(f"{str(start + i).rjust(width)}\t{line}" for i, line in enumerate(chunk))

        # Okunan dosyayı aider'ın sohbet bağlamına da ekle ki repo haritası ve
        # otomatik commit mantığı dosyadan haberdar olsun.
        ctx.coder.abs_fnames.add(str(p.resolve()))

        end = start + len(chunk) - 1
        header = f"{p} (satır {start}-{end}, toplam {len(lines)})"
        return _truncate(f"{header}\n{body}")


class WriteTool(PathTool):
    name = "Write"
    description = (
        "Bir dosyayı tamamen yazar; dosya varsa üzerine yazar. Var olan bir dosyanın "
        "üzerine yazmadan önce onu Read ile okumuş olmalısın. Kısmi değişiklikler için "
        "Write yerine Edit kullan."
    )
    mutating = True
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Yazılacak dosyanın yolu"},
            "content": {"type": "string", "description": "Dosyanın tam içeriği"},
        },
        "required": ["file_path", "content"],
    }

    def run(self, ctx, file_path, content):
        p = self.resolve(ctx, file_path)
        existed = p.exists()

        rel = os.path.relpath(p, ctx.root)
        verb = "üzerine yaz" if existed else "oluştur"
        if not ctx.confirm(self.name, rel, f"Dosyayı {verb}?"):
            return "Kullanıcı bu yazma işlemini reddetti. Devam etmeden önce ona danış."

        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(content, encoding="utf-8")
        except OSError as err:
            raise ToolError(f"{p} yazılamadı: {err}")

        abs_p = str(p.resolve())
        ctx.coder.abs_fnames.add(abs_p)
        if ctx.coder.aider_edited_files is not None:
            ctx.coder.aider_edited_files.add(rel)

        n = len(content.splitlines())
        return f"{'Güncellendi' if existed else 'Oluşturuldu'}: {rel} ({n} satır)"


class EditTool(PathTool):
    name = "Edit"
    description = (
        "Bir dosyada birebir string değişimi yapar. old_string dosyada bire bir ve "
        "TEK olarak eşleşmeli (girinti dahil); aksi halde işlem hata verir. Aynı "
        "metnin tüm örneklerini değiştirmek için replace_all kullan. Düzenlemeden "
        "önce dosyayı Read ile okumalısın."
    )
    mutating = True
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Düzenlenecek dosyanın yolu"},
            "old_string": {"type": "string", "description": "Değiştirilecek birebir metin"},
            "new_string": {"type": "string", "description": "Yerine yazılacak metin"},
            "replace_all": {
                "type": "boolean",
                "description": "Tüm eşleşmeleri değiştir (varsayılan false)",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    def run(self, ctx, file_path, old_string, new_string, replace_all=False):
        p = self.resolve(ctx, file_path)
        if not p.exists():
            raise ToolError(f"{p} yok. Yeni dosya için Write kullan.")
        if old_string == new_string:
            raise ToolError("old_string ile new_string aynı, değişiklik yok")

        try:
            text = p.read_text(encoding="utf-8")
        except OSError as err:
            raise ToolError(f"{p} okunamadı: {err}")

        count = text.count(old_string)
        if count == 0:
            raise ToolError(
                f"old_string {p} içinde bulunamadı. Dosyayı Read ile tekrar oku ve "
                "girintiyi birebir kopyala."
            )
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_string {p} içinde {count} kez geçiyor. Daha fazla çevre satır "
                "ekleyerek benzersizleştir ya da replace_all=true ver."
            )

        rel = os.path.relpath(p, ctx.root)
        if not ctx.confirm(self.name, rel, "Dosyayı düzenle?"):
            return "Kullanıcı bu düzenlemeyi reddetti. Devam etmeden önce ona danış."

        new_text = (
            text.replace(old_string, new_string)
            if replace_all
            else text.replace(old_string, new_string, 1)
        )
        try:
            p.write_text(new_text, encoding="utf-8")
        except OSError as err:
            raise ToolError(f"{p} yazılamadı: {err}")

        ctx.coder.abs_fnames.add(str(p.resolve()))
        if ctx.coder.aider_edited_files is not None:
            ctx.coder.aider_edited_files.add(rel)

        n = count if replace_all else 1
        return f"Düzenlendi: {rel} ({n} yer değiştirildi)"


class BashTool(Tool):
    name = "Bash"
    description = (
        "Bir kabuk komutu çalıştırır ve birleşik stdout/stderr çıktısını döndürür. "
        "Dosya okuma/arama için Bash yerine Read/Grep/Glob araçlarını tercih et. "
        "Komut her çalıştırmada kullanıcı onayına sunulur."
    )
    mutating = True
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Çalıştırılacak kabuk komutu"},
            "description": {
                "type": "string",
                "description": "Komutun ne yaptığının 5-10 kelimelik özeti",
            },
            "timeout": {
                "type": "integer",
                "description": "Saniye cinsinden zaman aşımı (varsayılan 120, en fazla 600)",
            },
        },
        "required": ["command"],
    }

    def run(self, ctx, command, description=None, timeout=120):
        if not command or not command.strip():
            raise ToolError("command boş olamaz")

        timeout = max(1, min(int(timeout or 120), 600))

        subject = command if not description else f"{command}\n  ({description})"
        if not ctx.confirm(self.name, subject, "Kabuk komutunu çalıştır?"):
            return "Kullanıcı bu komutu reddetti. Onsuz ilerlemeyi dene ya da ona danış."

        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=ctx.cwd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"Komut {timeout} saniyede zaman aşımına uğradı: {command}"
        except OSError as err:
            raise ToolError(f"komut başlatılamadı: {err}")

        out = (proc.stdout or "") + (proc.stderr or "")
        out = out.strip() or "(çıktı yok)"
        status = "" if proc.returncode == 0 else f"\n[çıkış kodu {proc.returncode}]"
        return _truncate(out + status)


def _walk_files(root, glob_pat=None):
    """SKIP_DIRS'i atlayarak dosyaları gez."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
        for fn in filenames:
            full = Path(dirpath) / fn
            if glob_pat:
                rel = os.path.relpath(full, root)
                if not (fnmatch.fnmatch(rel, glob_pat) or fnmatch.fnmatch(fn, glob_pat)):
                    continue
            yield full


class GlobTool(Tool):
    name = "Glob"
    description = (
        "Glob desenine uyan dosyaları bulur (ör. '**/*.py', 'src/**/*.ts'). Sonuçlar "
        "değiştirilme tarihine göre yeniden eskiye sıralanır."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Eşleştirilecek glob deseni"},
            "path": {
                "type": "string",
                "description": "Aranacak kök dizin (varsayılan: proje kökü)",
            },
        },
        "required": ["pattern"],
    }

    def run(self, ctx, pattern, path=None):
        root = Path(path).expanduser() if path else Path(ctx.root)
        if not root.is_absolute():
            root = Path(ctx.root) / root
        if not root.exists():
            raise ToolError(f"{root} yok")

        hits = list(_walk_files(root, pattern))
        if not hits:
            return f"'{pattern}' desenine uyan dosya yok ({root} altında)"

        hits.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        rels = [os.path.relpath(p, ctx.root) for p in hits[:200]]
        extra = f"\n... ve {len(hits) - 200} dosya daha" if len(hits) > 200 else ""
        return f"{len(hits)} eşleşme:\n" + "\n".join(rels) + extra


class GrepTool(Tool):
    name = "Grep"
    description = (
        "Dosya içeriklerinde regex araması yapar. output_mode='content' eşleşen "
        "satırları, 'files_with_matches' yalnızca dosya adlarını, 'count' dosya başına "
        "eşleşme sayısını döndürür. Mümkünse önce ripgrep kullanılır."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Aranacak regex deseni"},
            "path": {
                "type": "string",
                "description": "Aranacak dosya ya da dizin (varsayılan: proje kökü)",
            },
            "glob": {"type": "string", "description": "Dosyaları süzmek için glob, ör. '*.py'"},
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "Çıktı biçimi (varsayılan files_with_matches)",
            },
            "case_insensitive": {"type": "boolean", "description": "Büyük/küçük harf duyarsız ara"},
            "head_limit": {"type": "integer", "description": "İlk N sonucu döndür"},
        },
        "required": ["pattern"],
    }

    def run(
        self,
        ctx,
        pattern,
        path=None,
        glob=None,
        output_mode="files_with_matches",
        case_insensitive=False,
        head_limit=None,
    ):
        target = Path(path).expanduser() if path else Path(ctx.root)
        if not target.is_absolute():
            target = Path(ctx.root) / target
        if not target.exists():
            raise ToolError(f"{target} yok")

        cmd = ["rg", "--no-heading", "--color", "never"]
        if case_insensitive:
            cmd.append("-i")
        if output_mode == "files_with_matches":
            cmd.append("-l")
        elif output_mode == "count":
            cmd.append("-c")
        else:
            cmd.append("-n")
        if glob:
            cmd += ["--glob", glob]
        cmd += ["-e", pattern, str(target)]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=60)
            out = proc.stdout
            # rg eşleşme yoksa 1 döner; bu hata değil.
            if proc.returncode not in (0, 1):
                raise FileNotFoundError
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            out = self._python_fallback(ctx, pattern, target, glob, output_mode, case_insensitive)

        lines = [ln for ln in out.splitlines() if ln.strip()]
        if not lines:
            return f"'{pattern}' için eşleşme yok"
        if head_limit:
            lines = lines[: int(head_limit)]

        # Yollar proje köküne göreli olsun: mutlak yollar hem okunmuyor hem
        # bağlamda gereksiz yer kaplıyor.
        kok = str(Path(ctx.root).resolve()) + os.sep
        lines = [ln.replace(kok, "") for ln in lines]

        return _truncate("\n".join(lines))

    def _python_fallback(self, ctx, pattern, target, glob, output_mode, case_insensitive):
        """ripgrep yoksa saf Python ile ara."""
        import re

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error as err:
            raise ToolError(f"geçersiz regex: {err}")

        files = [target] if target.is_file() else _walk_files(target, glob)
        out = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            matches = [(i, ln) for i, ln in enumerate(text.splitlines(), 1) if rx.search(ln)]
            if not matches:
                continue
            if output_mode == "files_with_matches":
                out.append(str(f))
            elif output_mode == "count":
                out.append(f"{f}:{len(matches)}")
            else:
                out += [f"{f}:{i}:{ln}" for i, ln in matches]
        return "\n".join(out)
