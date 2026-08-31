"""Araç izin sistemi: kural tabanlı otomatik onay, reddetme ve soru sorma.

DEFAULT_ASK ve DEFAULT_DENY kuralları `Bash(...)` yazılsa bile uzak kabuğu
(`Ssh`) da kapsar; bkz. PermissionSet._rule_hits. Yani "ansible-playbook oto
modda bile sorulsun" kuralı sunucuda çalıştırılan ansible için de geçerli.

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

# Komut çalıştıran araçlar: kural deseni dosya yoluna değil komuta uygulanır.
COMMAND_TOOLS = ("Bash", "Ssh")

# Uzakta komut çalıştıranlar. Bunlarda yerel Bash(...) reddetme kuralları da
# geçerlidir; bkz. PermissionSet._rule_hits.
REMOTE_TOOLS = ("Ssh",)

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
    # Geri alınamaz ve felaketle sonuçlanan işlemler. Bunlar kullanıcı
    # açıkça istese bile çalıştırılmaz; gerçekten gerekiyorsa kullanıcı
    # komutu kendi kabuğunda çalıştırır.
    "Bash(rm -rf /*)",
    "Bash(rm -rf ~*)",
    "Bash(mkfs*)",
    "Bash(dd if=*)",
]

# Auto modda BİLE onay istenen kalıplar. DEFAULT_DENY'den farkı: kullanıcı
# "evet" derse çalışır. "Özel olarak söylenmedikçe yapılmasın, söylenirse
# yapılsın" gereksiniminin karşılığı budur — reboot bunun tipik örneği.
#
# Kullanıcının kendi allow kuralı buradaki bir kalıbı ezebilir; sıra
# decide() içinde açıkça allow -> default-ask şeklindedir.
DEFAULT_ASK = [
    # Makineyi kapatan/başlatan işlemler
    "Bash(reboot:*)",
    "Bash(shutdown:*)",
    "Bash(init:*)",
    # Yetki yükseltme
    "Bash(sudo:*)",
    "Bash(doas:*)",
    # Kod tabanının dışına çıkan ya da geri alınamayan git işlemleri
    "Bash(git push:*)",
    "Bash(git reset --hard:*)",
    "Bash(git clean -fdx:*)",
    # İnternetten indirip çalıştırma. Zincir parçalara ayrıldığı için
    # "curl x | sh" komutunda "sh" parçası burada yakalanır; argümanlı
    # "bash script.sh" ise tam eşleşme olmadığından etkilenmez.
    "Bash(sh)",
    "Bash(bash)",
    "Bash(zsh)",
    # --- Tek makineyi değil FİLOYU etkileyenler ---------------------------
    # ansible-playbook'ta --limit yoksa envanterin tamamına dokunur. Oto
    # modda bu, tek bir araç çağrısıyla yüzlerce sunucuyu değiştirmek
    # demekti. ansible becerisi bunu zaten "önce --list-hosts, sonra
    # --check" diye anlatıyor; kural o disiplini zorunlu kılıyor.
    "Bash(ansible-playbook:*)",
    "Bash(ansible:*)",
    # --- Sunucu durumunu değiştirenler ------------------------------------
    # Paket kurma/kaldırma ve servis durdurma geri alınabilir ama üretimde
    # kesinti demek. Salt-okunur olanlar (dnf list, systemctl status,
    # is-active) kapsam dışı: onlar bu öneklere uymuyor.
    "Bash(dnf install:*)",
    "Bash(dnf remove:*)",
    "Bash(dnf update:*)",
    "Bash(dnf upgrade:*)",
    "Bash(yum install:*)",
    "Bash(yum remove:*)",
    "Bash(yum update:*)",
    "Bash(systemctl stop:*)",
    "Bash(systemctl restart:*)",
    "Bash(systemctl disable:*)",
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

        if tool_name in COMMAND_TOOLS:
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
    # DİKKAT: lstrip("./") karakter siler, önek değil. ".env" yolunu "env"
    # yapıyordu ve Edit(.env) gibi bir reddetme kuralı sessizce ıskalıyordu.
    if path.startswith("./"):
        path = path[2:]
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

    def __init__(self, allow=None, deny=None, ask=None, mode=MODE_ASK, use_default_deny=True):
        if mode not in MODES:
            raise ValueError(f"geçersiz izin modu: {mode!r}. Geçerli: {', '.join(MODES)}")
        self.mode = mode
        self.allow = _parse_rules(allow, "allow")
        self.deny = _parse_rules(deny, "deny")
        self.ask = _parse_rules(ask, "ask")
        if use_default_deny:
            self.deny += _parse_rules(DEFAULT_DENY, "varsayılan deny")
            self.ask += _parse_rules(DEFAULT_ASK, "varsayılan ask")

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

        # Auto modu yenen ama kullanıcının açık iznine yenilen orta katman.
        for rule in self.ask:
            if self._rule_hits(rule, tool_name, args):
                return ASK

        if self.mode == MODE_AUTO:
            return ALLOW

        return ASK

    def _rule_hits(self, rule, tool_name, args, require_all_parts=False):
        """Kuralı çağrıya uygula; kabuk zincirlerini parça parça değerlendir."""
        if tool_name not in COMMAND_TOOLS:
            return rule.matches(tool_name, args)

        # Bir Bash(...) reddi uzak kabuğu da kapsamalı. "rm -rf /" yerelde
        # yasakken Ssh üzerinden serbest kalırsa yasak hiçbir şey ifade etmez;
        # oto modda bu, tek bir araç çağrısıyla sunucu silmek demekti.
        # Yalnızca REDDETME yönünde genişletiyoruz: izni genişletmek güvenli
        # değil, reddi genişletmek her zaman güvenli taraf.
        if rule.tool != tool_name:
            if require_all_parts or tool_name not in REMOTE_TOOLS:
                return False
            if rule.tool != "Bash":
                return False
            tool_name = "Bash"

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
    """Kullanıcı 'bir daha sorma' dediğinde önerilecek kural metni.

    Komut çalıştıran araçlarda kural MUTLAKA komuta göre daraltılır. Çıplak
    "Ssh" kuralı, tek bir "bir daha sorma" yanıtıyla tanımlı her sunucuda her
    uzak komutu onaysız hâle getiriyordu.
    """
    if tool_name in COMMAND_TOOLS:
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


def load_permissions(
    project_root, mode=MODE_ASK, extra_allow=None, extra_deny=None, extra_ask=None
):
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
        ask:
          - Bash(dnf install:*)

    'deny' asla çalıştırmaz. 'ask' auto modda bile onay ister ama kullanıcı
    onaylarsa çalışır; 'allow' onu da ezer.
    """
    from pathlib import Path

    import yaml

    allow = list(extra_allow or [])
    deny = list(extra_deny or [])
    ask = list(extra_ask or [])
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
        ask += data.get("ask") or []
        if data.get("mode"):
            file_mode = data["mode"]

    # CLI bayrağı dosyadaki modu yener; dosya yalnızca varsayılanı değiştirir.
    if mode == MODE_ASK and file_mode:
        mode = file_mode

    return PermissionSet(allow=allow, deny=deny, ask=ask, mode=mode)
