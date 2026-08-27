"""Araç izin sistemi: kural tabanlı otomatik onay, reddetme ve soru sorma.

Kural sözdizimi Claude Code'un settings.json izinlerine benzer:

    Read                    -> Read aracının her çağrısı
    Bash(git diff:*)        -> "git diff" ile başlayan her komut
    Bash(npm test)          -> tam olarak "npm test"
    Write(src/**)           -> src altındaki dosyalara yazma
    Edit(*.py)              -> .py dosyalarını düzenleme

Reddetme her zaman izni yener. Kabuk komutlarında `&&`, `||`, `;`, `|` ile
zincirlenmiş her parça ayrı ayrı değerlendirilir: `git diff && rm -rf /`
komutu `Bash(git diff:*)` kuralıyla onaylanmaz.
"""

import fnmatch
import re
import shlex

# Kabuk zincirleme operatörleri. Bir komut bunlarla bölünüyorsa her parçanın
# ayrı ayrı izinli olması gerekir.
_CHAIN = re.compile(r"&&|\|\||;|(?<!\|)\|(?!\|)")

# Komut ikamesi içeren her şey otomatik onaydan muaf tutulur: içeriği statik
# olarak değerlendirilemez.
_SUBSTITUTION = re.compile(r"\$\(|`|<\(")

ALLOW = "allow"
DENY = "deny"
ASK = "ask"

# İzin modları
MODE_PLAN = "plan"  # yan etkili araçlar hiç sunulmaz
MODE_ASK = "ask"  # yan etkili araçlarda onay sor (varsayılan)
MODE_AUTO = "auto"  # reddedilmedikçe otomatik onayla

MODES = (MODE_PLAN, MODE_ASK, MODE_AUTO)

# Auto modda bile daima onay istenen kalıplar. Geri alınamaz ya da kod
# tabanının dışına çıkan işlemler burada.
# Not: ':*' önek eşleşmesi sözcük sınırı arar, yani "mkfs:*" kuralı
# "mkfs.ext4" komutunu YAKALAMAZ. Alt komut adı noktayla ya da eşittir
# işaretiyle devam eden komutlarda glob ('*') kullanmak gerekiyor.
DEFAULT_DENY = [
    # Geri alınamaz dosya silme
    "Bash(rm -rf /*)",
    "Bash(rm -rf ~*)",
    # Sistem düzeyi
    "Bash(sudo:*)",
    "Bash(doas:*)",
    "Bash(shutdown:*)",
    "Bash(reboot:*)",
    "Bash(mkfs*)",
    "Bash(dd if=*)",
    # İnternetten indirip çalıştırma. Zincir parçalara ayrıldığı için
    # "curl x | sh" komutunda "sh" parçası burada yakalanır; argümanlı
    # "bash script.sh" ise tam eşleşme olmadığından etkilenmez.
    "Bash(sh)",
    "Bash(bash)",
    "Bash(zsh)",
    # Kod tabanının dışına çıkan ya da geri alınamayan git işlemleri
    "Bash(git push:*)",
    "Bash(git reset --hard:*)",
    "Bash(git clean -fdx:*)",
]


class Rule:
    """Tek bir izin kuralı: araç adı ve isteğe bağlı desen."""

    def __init__(self, text):
        self.raw = text.strip()
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?:\((.*)\))?$", self.raw, re.DOTALL)
        if not m:
            raise ValueError(f"geçersiz izin kuralı: {text!r}")
        self.tool = m.group(1)
        self.pattern = m.group(2)

    def matches(self, tool_name, args):
        if self.tool != tool_name:
            return False
        if self.pattern is None:
            return True

        if tool_name == "Bash":
            return self._match_command(args.get("command", ""))

        # Yol tabanlı araçlar: deseni dosya yoluna uygula.
        path = args.get("file_path") or args.get("path") or args.get("pattern") or ""
        return _match_path(self.pattern, path)

    def _match_command(self, command):
        """Tek bir kabuk parçasını desene karşı sına."""
        pat = self.pattern.strip()
        cmd = command.strip()

        if pat.endswith(":*"):
            prefix = pat[:-2].strip()
            if cmd == prefix:
                return True
            # Önek eşleşmesi sözcük sınırında olmalı: "git diff" kuralı
            # "git diff-tree" komutunu kapsamamalı.
            return cmd.startswith(prefix) and cmd[len(prefix)] in " \t"

        if "*" in pat or "?" in pat or "[" in pat:
            return fnmatch.fnmatch(cmd, pat)

        return cmd == pat

    def __repr__(self):
        return f"Rule({self.raw!r})"


def _match_path(pattern, path):
    """Yolu glob desenine karşı sına; '**' alt dizinleri de kapsar."""
    if not path:
        return False
    path = path.lstrip("./")
    if fnmatch.fnmatch(path, pattern):
        return True
    # 'src/**' deseni 'src/a/b.py' kadar 'src/b.py' yolunu da kapsamalı.
    if pattern.endswith("/**"):
        base = pattern[:-3]
        return path == base or path.startswith(base + "/")
    return False


def split_command(command):
    """Zincirlenmiş kabuk komutunu parçalarına ayır."""
    parts = [p.strip() for p in _CHAIN.split(command)]
    return [p for p in parts if p]


def _parse_rules(items, source):
    rules = []
    for item in items or []:
        try:
            rules.append(Rule(item))
        except ValueError as err:
            raise ValueError(f"{source}: {err}")
    return rules


class PermissionSet:
    """Kural listelerini tutar ve bir araç çağrısı için karar üretir."""

    def __init__(self, allow=None, deny=None, mode=MODE_ASK, use_default_deny=True):
        if mode not in MODES:
            raise ValueError(f"geçersiz izin modu: {mode!r}. Geçerli: {', '.join(MODES)}")
        self.mode = mode
        self.allow = _parse_rules(allow, "allow")
        self.deny = _parse_rules(deny, "deny")
        if use_default_deny:
            self.deny += _parse_rules(DEFAULT_DENY, "varsayılan deny")

    def add_session_allow(self, rule_text):
        """Kullanıcı 'bir daha sorma' dediğinde oturumluk kural ekle."""
        self.allow.append(Rule(rule_text))

    def decide(self, tool_name, args, mutating):
        """ALLOW, DENY ya da ASK döndür."""
        # Reddetme her zaman önce değerlendirilir ve her şeyi yener.
        for rule in self.deny:
            if self._rule_hits(rule, tool_name, args):
                return DENY

        if not mutating:
            # Salt-okunur araçlar hiçbir zaman onay istemez.
            return ALLOW

        for rule in self.allow:
            if self._rule_hits(rule, tool_name, args, require_all_parts=True):
                return ALLOW

        if self.mode == MODE_AUTO:
            return ALLOW

        return ASK

    def _rule_hits(self, rule, tool_name, args, require_all_parts=False):
        """Kuralı çağrıya uygula; kabuk zincirlerini parça parça değerlendir."""
        if tool_name != "Bash":
            return rule.matches(tool_name, args)

        command = args.get("command", "")

        # Komut ikamesi statik olarak çözülemez; otomatik onaya asla girmesin.
        if require_all_parts and _SUBSTITUTION.search(command):
            return False

        parts = split_command(command)
        if not parts:
            return False

        if require_all_parts:
            # İzin için: her parça izinli olmalı.
            return all(rule.matches(tool_name, dict(command=p)) for p in parts)

        # Reddetme için: tek bir parçanın eşleşmesi yeter.
        return any(rule.matches(tool_name, dict(command=p)) for p in parts)


def matches_any(rules, tool_name, args):
    """Yardımcı: kural listesinden herhangi biri eşleşiyor mu."""
    return any(r.matches(tool_name, args) for r in rules)


def suggest_rule(tool_name, args):
    """Kullanıcı 'bir daha sorma' dediğinde önerilecek kural metni."""
    if tool_name == "Bash":
        command = (args.get("command") or "").strip()
        parts = split_command(command)
        base = parts[0] if parts else command
        try:
            tokens = shlex.split(base)
        except ValueError:
            tokens = base.split()
        if not tokens:
            return tool_name
        # "git diff --stat" -> "Bash(git diff:*)" : ilk iki sözcüğü al ki
        # kural ne fazla dar ne fazla geniş olsun.
        head = (
            " ".join(tokens[:2]) if len(tokens) > 1 and not tokens[1].startswith("-") else tokens[0]
        )
        return f"{tool_name}({head}:*)"
    return tool_name


def load_permissions(project_root, mode=MODE_ASK, extra_allow=None, extra_deny=None):
    """İzin kurallarını yapılandırma dosyalarından yükle.

    Aranan dosyalar, sonra gelen öncekine eklenir:
      1. ~/.aider/permissions.yml   (kişisel, tüm projelerde geçerli)
      2. <proje>/.aider/permissions.yml  (projeye özgü, depoya girer)

    Beklenen biçim:
        mode: ask
        allow:
          - Bash(git diff:*)
        deny:
          - Bash(npm publish:*)
    """
    from pathlib import Path

    import yaml

    allow = list(extra_allow or [])
    deny = list(extra_deny or [])
    file_mode = None

    candidates = [
        Path.home() / ".aider" / "permissions.yml",
        Path(project_root) / ".aider" / "permissions.yml",
    ]

    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as err:
            raise ValueError(f"{path} okunamadı: {err}")
        if not isinstance(data, dict):
            raise ValueError(f"{path}: en üst düzeyde bir sözlük bekleniyordu")

        allow += data.get("allow") or []
        deny += data.get("deny") or []
        if data.get("mode"):
            file_mode = data["mode"]

    # CLI bayrağı dosyadaki modu yener; dosya yalnızca varsayılanı değiştirir.
    if mode == MODE_ASK and file_mode:
        mode = file_mode

    return PermissionSet(allow=allow, deny=deny, mode=mode)
