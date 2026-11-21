
from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Pattern, Tuple, Union

FOLDER_MOVES: Tuple[Tuple[str, str], ...] = (
    ("src/cplugs", "src/plugins"),
    ("web/src/cplugs", "web/src/plugins"),
)

OLD_NAME = "cplugs"
NEW_NAME = "plugins"

WEB_SRC_PARTS: Tuple[str, ...] = ("web", "src")

SPECIFIER_SUFFIXES = frozenset({".ts", ".js", ".mjs", ".cjs", ".svelte", ".css", ".html"})

MAX_TEXT_BYTES = 8 * 1024 * 1024


def glob_to_regex(glob: str) -> Pattern[str]:
    out: List[str] = []
    i = 0
    while i < len(glob):
        ch = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "{":
            end = glob.index("}", i)
            out.append("(?:" + "|".join(re.escape(p) for p in glob[i + 1:end].split(",")) + ")")
            i = end
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$")


EXCLUDED_GLOBS: Tuple[str, ...] = (
    "client/dist/**/*",
    "**/node_modules/**/*",
    "docs/DECISIONS.md",
    "docs/LESSONS.md",
    "docs/claude-md-archive-*.md",
    "docs/archive/**/*",
    "docs/incidents/**/*",
    "docs/rename-carnivore.md",
    ".claude/TODO-*.md",
    ".claude/handoff-*.md",
    ".claude/notes/**/*",
    ".claude/sessions/**/*",
    ".claude/tasks/**/*",
    ".claude/logs/**/*",
    "features/changes/**/*",
    "design/boards/*/**/*",
    "features/index.json",
    "features/schema.json",
    "FEATURES.md",
    "**/cplug.json",
    "**/carnivore.json",
    "src/{cplugs,plugins}/order.json",
    "scripts/maintenance/rename_plugin_folders.py",
    "scripts/maintenance/plugin_rename_rules.py",
    "tests/python/maintenance/test_rename_plugin_folders.py",
)
EXCLUDED_REGEXES: Tuple[Pattern[str], ...] = tuple(glob_to_regex(g) for g in EXCLUDED_GLOBS)

PINNED_LINES: Tuple[Tuple[Pattern[str], Pattern[str]], ...] = (
    (glob_to_regex("src/{cplugs,plugins}/sdk/ownership.py"), re.compile(r"web_root, py_tests = ")),
    (glob_to_regex("src/{cplugs,plugins}/sdk/ownership.py"), re.compile(r"web/src/cplugs/<id>/")),
    (glob_to_regex("docs/cplugs.md"), re.compile(r"\| `owns\.(?:tests|style_guide)` \|\s*$")),
    (glob_to_regex("docs/cplugs.md"), re.compile(r"^\*\*Manifest `owns` values keep")),
    (glob_to_regex("**/*"), re.compile(r"# owns-contract\b")),
)

INVARIANT_PATTERNS: Tuple[Tuple[str, Pattern[str]], ...] = (
    ("manifest file cplug.json", re.compile(r"cplug\.json")),
    ("manifest file carnivore.json", re.compile(r"carnivore\.json")),
    ("route /api/v1/cplugs", re.compile(r"api/v1/cplugs")),
    ("route /cplug-owner", re.compile(r"/cplug-owner")),
    ("test folder tests/python/cplugs", re.compile(r"tests/python/cplugs")),
    ("doc docs/cplugs.md", re.compile(r"docs/cplugs\.md")),
    ("doc docs/cplug-platform.md", re.compile(r"docs/cplug-platform\.md")),
    ("host router prefix /cplugs", re.compile(r"prefix=\"/cplugs\"")),
)


@dataclass(frozen=True)
class TextRule:

    name: str
    pattern: Pattern[str]
    replacement: Union[str, Callable[["re.Match[str]"], str]]


TEXT_RULES: Tuple[TextRule, ...] = (
    TextRule("dotted module path", re.compile(r"\bsrc\.cplugs(?![A-Za-z0-9_])"), "src.plugins"),
    TextRule("slash path", re.compile(r"(?<![\w-])src/cplugs(?![A-Za-z0-9_-])"), "src/plugins"),
    TextRule("bare code-file path", re.compile(r"(?<![\w/.<>$-])cplugs/(?=[\w.-]+(?:/[\w.-]+)*\.(?:py|ts|svelte|css|js|mjs|sh)(?![\w-]))"), "plugins/"),
    TextRule("regex literal over a code path", re.compile(r"(?<=[^\\]/)cplugs(?=\\/\(\[\^/\]\+\)\\/)"), "plugins"),
    TextRule("joined path literals", re.compile(r"""(["'])src\1(\)?\s*[/,]\s*)(["'])cplugs\3"""), r"\1src\1\2\3plugins\3"),
)

FILE_PATCHES: Tuple[Tuple[Pattern[str], Pattern[str], str, str], ...] = (
    (glob_to_regex("scripts/plugin/check.py"), re.compile(r'(SCHEMA_DIR\.parents\[1\] / )"cplugs"'), r'\1"plugins"', "plugin folder beside the schema"),
    (glob_to_regex("src/core/notifications/catalog_lines.py"), re.compile(r'(parents\[2\] / )"cplugs"'), r'\1"plugins"', "notify catalog slices root"),
    (glob_to_regex("tests/helpers/style_guide_inventory.py"), re.compile(r'(WEB_SRC / )"cplugs"'), r'\1"plugins"', "web plugin folder in the guide inventory"),
    (glob_to_regex("tests/python/cplugs/test_one_registry_writer.py"), re.compile(r'(SRC / )"cplugs"( / "host")'), r'\1"plugins"\2', "registry writer source files"),
    (glob_to_regex("tests/python/cplugs/test_cplug_boundaries.py"), re.compile(r'(rel\.parts\[0\] == )"cplugs"'), r'\1"plugins"', "core importer scan skips the ship list"),
    (glob_to_regex("web/src/{cplugs,plugins}/boundaries.test.ts"), re.compile(r"(const CPLUGS_DIR = )'cplugs'"), r"\1'plugins'", "web boundary scan folder"),
    (glob_to_regex("web/src/{cplugs,plugins}/boundaries.test.ts"), re.compile(r"\.\./\.\./cplugs/"), "../../plugins/", "synthetic imports in the boundary self-test"),
    (glob_to_regex("tests/python/cplugs/test_cplug_ownership.py"), re.compile(r"if not \(ROOT / t\)\.exists\(\)\]$", re.M),
     'if not (ROOT / t.replace("web/src/cplugs/", "web/src/plugins/", 1)).exists()]  # owns-contract: manifests keep the old prefix', "owns paths exist"),
    (glob_to_regex("tests/python/cplugs/test_cplug_follow_ups.py"), re.compile(r"declared = set\(DEFINITIONS\[pid\]\.manifest\.owns\.style_guide\)$", re.M),
     'declared = {p.replace("web/src/cplugs/", "web/src/plugins/", 1) for p in DEFINITIONS[pid].manifest.owns.style_guide}  # owns-contract: manifests keep the old prefix', "owns.style_guide vs registry rows"),
    (glob_to_regex("tests/python/cplugs/removability.py"), re.compile(r"declared = \{p for p in d\.manifest\.owns\.style_guide\}$", re.M),
     'declared = {p.replace("web/src/cplugs/", "web/src/plugins/", 1) for p in d.manifest.owns.style_guide}  # owns-contract: manifests keep the old prefix', "owns.style_guide vs style-guide.json"),
    (glob_to_regex("src/{cplugs,plugins}/sdk/ownership.py"), re.compile(r"``src/cplugs/<id>/`` and ``web/src/cplugs/<id>/``"),
     "``src/plugins/<id>/`` and ``web/src/cplugs/<id>/``", "ownership docstring: the code folder moved, the owns prefix did not"),
    (glob_to_regex("docs/cplugs.md"), re.compile(r"(?<=\|\n\n)(\*\*Core reaches a plugin only through the seams:\*\*)"),
     "**Manifest `owns` values keep the `cplugs` prefix** (`web/src/cplugs/<id>/`): the code folders are now `src/plugins/` and `web/src/plugins/`, "
     "but a manifest is a field contract every app version since 1.16.2 reads, so `owns.tests` and `owns.style_guide` are still written and "
     "validated with the old prefix and the tests translate them to where the file lives now.\n\n\\1", "docs: owns values keep the cplugs prefix"),
    (glob_to_regex("scripts/gate/field_installs.py"), re.compile(r"^(    import inspect\n)(?!    import importlib)", re.M), "\\1    import importlib\n",
     "field_installs worker: import importlib"),
    (glob_to_regex("scripts/gate/field_installs.py"),
     re.compile(r'(    app_version = json\.loads\(\(core / "macOS" / "package\.json"\)\.read_text\(encoding="utf-8"\)\)\["version"\]\n)(?!    # plugin_dir)'),
     '\\1    # plugin_dir: the plugin folder THIS core really has (a 1.16.x core names it cplugs, a renamed one plugins); both are probed, never aliased\n'
     '    plugin_dir = next((n for n in ("plugins", "cplugs") if (core / "src" / n / "host" / "install_gates.py").is_file()), "plugins")\n',
     "field_installs worker: probe the core's own plugin folder"),
    (glob_to_regex("scripts/gate/field_installs.py"), re.compile(r'core / "src" / "plugins" / job\["name"\]'), 'core / "src" / plugin_dir / job["name"]',
     "field_installs worker: builtin lookup in the core's own layout"),
    (glob_to_regex("scripts/gate/field_installs.py"), re.compile(r"^( +)from src\.plugins\.host import install_gates$", re.M),
     '\\1install_gates = importlib.import_module(f"src.{plugin_dir}.host.install_gates")  # whichever layout this core has',
     "field_installs worker: import the gates from the core's own layout"),
    (glob_to_regex("scripts/design/check_top_down.sh"), re.compile(r"\(lib\|opscenter\|cplugs\|"), "(lib|opscenter|plugins|", "gate's web folder list"),
)


WEB_RELATIVE_SUFFIXES = frozenset({".ts", ".js", ".mjs", ".cjs", ".svelte", ".css"})
WEB_RELATIVE_ROOTS = ("web/", "tests/")
WEB_RULE_NAME = "web/src-relative path"


def web_children(files: Iterable[str]) -> frozenset:
    names = set()
    for f in files:
        for prefix in ("web/src/" + OLD_NAME + "/", "web/src/" + NEW_NAME + "/"):
            if f.startswith(prefix):
                names.add(f[len(prefix):].split("/")[0])
    return frozenset(names)


@functools.lru_cache(maxsize=4)
def web_relative_pattern(children: frozenset) -> Optional[Pattern[str]]:
    if not children:
        return None
    alt = "|".join(re.escape(c) for c in sorted(children, key=len, reverse=True))
    return re.compile(rf"(?<![\w/.<>$-])cplugs/(?=(?:{alt})(?![\w-]))")


def web_rule_applies(path: str) -> bool:
    return path.startswith(WEB_RELATIVE_ROOTS) and PurePosixPath(path).suffix in WEB_RELATIVE_SUFFIXES


def is_excluded(path: str) -> bool:
    return any(rx.match(path) for rx in EXCLUDED_REGEXES)


def is_pinned_line(path: str, line: str) -> bool:
    return any(pf.match(path) and pl.search(line) for pf, pl in PINNED_LINES)


def new_path(path: str) -> str:
    for old, new in FOLDER_MOVES:
        if path == old or path.startswith(old + "/"):
            return new + path[len(old):]
    return path


def old_path(path: str) -> str:
    for old, new in FOLDER_MOVES:
        if path == new or path.startswith(new + "/"):
            return old + path[len(new):]
    return path


def in_old_folder(path: str) -> bool:
    return any(path == old or path.startswith(old + "/") for old, _ in FOLDER_MOVES)


def rewrite_specifier(spec: str, importer_old_dir: str) -> Optional[str]:
    stack = list(PurePosixPath(importer_old_dir).parts)
    parts = spec.split("/")
    changed = False
    for idx, seg in enumerate(parts):
        if seg == "..":
            if not stack:
                return None
            stack.pop()
        elif seg and seg != ".":
            if seg == OLD_NAME and tuple(stack) == WEB_SRC_PARTS:
                parts[idx] = NEW_NAME
                changed = True
            stack.append(seg)
    return "/".join(parts) if changed else None


SPECIFIER_RE = re.compile(r"""(?<=['"`(])(\.{1,2}/[^'"`()\s]*?\bcplugs\b[^'"`()\s]*)""")


def rewrite_specifiers(text: str, importer_old_dir: str) -> Tuple[str, int]:
    count = 0

    def sub(match: "re.Match[str]") -> str:
        nonlocal count
        fixed = rewrite_specifier(match.group(1), importer_old_dir)
        if fixed is None:
            return match.group(0)
        count += 1
        return fixed

    return SPECIFIER_RE.sub(sub, text), count


def apply_text_rules(path: str, text: str, counts: Dict[str, int], children: frozenset = frozenset()) -> str:
    old_dir = str(PurePosixPath(path).parent)
    is_spec_file = PurePosixPath(path).suffix in SPECIFIER_SUFFIXES
    web_rx = web_relative_pattern(children) if web_rule_applies(path) else None
    out: List[str] = []
    for line in text.splitlines(keepends=True):
        if is_pinned_line(new_path(path), line):
            out.append(line)
            continue
        if web_rx is not None:
            line, hits = web_rx.subn("plugins/", line)
            if hits:
                counts[WEB_RULE_NAME] = counts.get(WEB_RULE_NAME, 0) + hits
        for rule in TEXT_RULES:
            line, hits = rule.pattern.subn(rule.replacement, line)
            if hits:
                counts[rule.name] = counts.get(rule.name, 0) + hits
        if is_spec_file:
            line, hits = rewrite_specifiers(line, old_dir)
            if hits:
                counts["relative import specifier"] = counts.get("relative import specifier", 0) + hits
        out.append(line)
    result = "".join(out)
    for file_rx, rx, repl, why in FILE_PATCHES:
        if file_rx.match(new_path(path)):
            result, hits = rx.subn(repl, result)
            if hits:
                counts[f"patch: {why}"] = counts.get(f"patch: {why}", 0) + hits
    return result


def leftover_hits(path: str, text: str, children: frozenset = frozenset()) -> List[str]:
    hits: List[str] = []
    is_spec_file = PurePosixPath(path).suffix in SPECIFIER_SUFFIXES
    web_rx = web_relative_pattern(children) if web_rule_applies(path) else None
    for number, line in enumerate(text.splitlines(), start=1):
        if is_pinned_line(path, line):
            continue
        if web_rx is not None and web_rx.search(line):
            hits.append(f"line {number}: {WEB_RULE_NAME}")
        hits += [f"line {number}: {r.name}" for r in TEXT_RULES if r.pattern.search(line)]
        if is_spec_file and rewrite_specifiers(line, str(PurePosixPath(path).parent))[1]:
            hits.append(f"line {number}: relative import specifier")
        hits += [f"line {number}: patch ({why})" for fr, rx, _, why in FILE_PATCHES if fr.match(path) and rx.search(line)]
    return hits


def invariant_counts(texts: Iterable[str]) -> Dict[str, int]:
    totals = {name: 0 for name, _ in INVARIANT_PATTERNS}
    for text in texts:
        for name, rx in INVARIANT_PATTERNS:
            totals[name] += len(rx.findall(text))
    return totals
