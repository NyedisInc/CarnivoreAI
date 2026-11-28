
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Pattern, Tuple

from scripts.maintenance.plugin_rename_rules import EXCLUDED_GLOBS as FOLDER_RENAME_EXCLUDED
from scripts.maintenance.plugin_rename_rules import MAX_TEXT_BYTES, TextRule, glob_to_regex

__all__ = ["MAX_TEXT_BYTES"]

OLD_NAME = "huddle"
NEW_NAME = "taskmanager"

FOLDER_MOVES: Tuple[Tuple[str, str], ...] = (
    ("src/plugins/huddle", "src/plugins/taskmanager"),
    ("web/src/plugins/huddle", "web/src/plugins/taskmanager"),
    ("tests/python/cplugs/huddle", "tests/python/cplugs/taskmanager"),
)

MOVED_PARENTS: Tuple[Tuple[str, ...], ...] = tuple(tuple(PurePosixPath(old).parent.parts) for old, _ in FOLDER_MOVES)

SPECIFIER_SUFFIXES = frozenset({".ts", ".js", ".mjs", ".cjs", ".svelte", ".css", ".html"})

TOPICS: Tuple[str, ...] = ("list", "delta", "cards", "focus", "held", "sendq", "told", "progress", "prefs")
_TOPIC_ALT = "|".join(TOPICS)

EXCLUDED_GLOBS: Tuple[str, ...] = tuple(g for g in FOLDER_RENAME_EXCLUDED if g not in ("**/cplug.json", "**/carnivore.json", "src/{cplugs,plugins}/order.json")) + (
    "scripts/maintenance/huddle_rename_rules.py",
    "tests/python/maintenance/test_huddle_rename_rules.py",
    "tests/python/cplugs/test_task_manager_id.py",
    "hosted/**/*",
    "docs/task-manager-rename.md",
)
EXCLUDED_REGEXES: Tuple[Pattern[str], ...] = tuple(glob_to_regex(g) for g in EXCLUDED_GLOBS)

INVARIANT_PATTERNS: Tuple[Tuple[str, Pattern[str]], ...] = (
    ("MCP tool names task_manager_*", re.compile(r"\btask_manager_[a-z][a-z_]*")),
    ("huddle_* names (old tools, tables, columns)", re.compile(r"\bhuddle_[a-z]\w*")),
    ("database file huddle.db", re.compile(r"huddle\.db")),
    ("widget id huddle.chat", re.compile(r"(?<!\"widgets\": \[\")(?<!name: ')huddle\.chat(?!\": \{)")),
    ("tab id huddle", re.compile(r"TASK_MANAGER_TAB = 'huddle'|\"tabs\": \[\"huddle\"\]")),
    ("Pack key huddle", re.compile(r"manifest\[[\"']huddle[\"']\]|[\"']huddle[\"']: task_manager_side")),
    ("route /cplugs/huddle", re.compile(r"cplugs/huddle(?![\w-])(?<!python/cplugs/huddle)(?<!src/cplugs/huddle)")),
    ("string keys cplug.huddle.*", re.compile(rf"cplug\.huddle\.(?!(?:{_TOPIC_ALT})(?![\w.-]))")),
    ("bundled skill huddle", re.compile(r"carnivore/huddle\b|bundled/huddle\b|register_guide\(\"huddle\"|extensions\(\"huddle\"")),
    ("browser storage keys", re.compile(r"(?:cloude|carnivore)\.huddle\.")),
    ("channel kind huddle", re.compile(r"CHANNEL_META_KIND: \"huddle\"")),
)

TEXT_RULES: Tuple[TextRule, ...] = (
    TextRule("dotted module path", re.compile(r"\b(src\.plugins|tests\.python\.cplugs)\.huddle(?![A-Za-z0-9_])"), rf"\1.{NEW_NAME}"),
    TextRule("slash path", re.compile(r"(?<![\w-])(src/plugins|tests/python/cplugs)/huddle(?![\w-])"), rf"\1/{NEW_NAME}"),
    TextRule("owns contract path", re.compile(r"(?<![\w-])web/src/cplugs/huddle/"), f"web/src/cplugs/{NEW_NAME}/"),
    TextRule("bare code-file path", re.compile(r"(?<![\w/.<>$-])plugins/huddle/(?=[\w.-]+(?:/[\w.-]+)*\.(?:py|ts|svelte|css|js|mjs|sh|json)(?![\w-]))"),
             f"plugins/{NEW_NAME}/"),
    TextRule("joined path literals", re.compile(r"""(["'])plugins\1(\s*/\s*)(["'])huddle\3"""), r"\1plugins\1\2\3taskmanager\3"),
    TextRule("plugin folder constant", re.compile(r"""\b(PLUGINS|CPLUGS) / (["'])huddle\2"""), r"\1 / \2taskmanager\2"),
    TextRule("package import", re.compile(r"\bfrom src\.plugins import huddle\b(?= as )"), f"from src.plugins import {NEW_NAME}"),
    TextRule("package import, unaliased", re.compile(r"\bfrom src\.plugins import huddle$", re.M), f"from src.plugins import {NEW_NAME} as huddle"),
    TextRule("web plugin object", re.compile(r"\bhuddleCplug\b"), f"{NEW_NAME}Cplug"),
    TextRule("push topic", re.compile(rf"\bcplug\.huddle\.(?=(?:{_TOPIC_ALT})(?![\w.-]))"), f"cplug.{NEW_NAME}."),
    TextRule("plugin router and context", re.compile(r"\b(cplug_router|cplug_context)\(\"huddle\"\)"), rf'\1("{NEW_NAME}")'),
    TextRule("public route helper", re.compile(r"\b(add_public_get|add_public_post)\(router, \"huddle\","), rf'\1(router, "{NEW_NAME}",'),
    TextRule("plugin lookup", re.compile(r"\bruntime\.find\(\"huddle\"\)"), f'runtime.find("{NEW_NAME}")'),
    TextRule("web plugin page", re.compile(r"\b(openCplugPage|registerCplugPage|openPluginSettings)\('huddle'"), rf"\1('{NEW_NAME}'"),
)


def _patch(glob: str, rx: str, repl: str, why: str, flags: int = 0) -> Tuple[Pattern[str], Pattern[str], str, str]:
    return glob_to_regex(glob), re.compile(rx, flags), repl, why


FILE_PATCHES: Tuple[Tuple[Pattern[str], Pattern[str], str, str], ...] = (
    _patch("src/plugins/{huddle,taskmanager}/cplug.json", r'^  "id": "huddle",\n', '  "id": "taskmanager",\n  "renamed_from": "huddle",\n'
           '  "renamed_from_keeps": ["strings", "widgets"],\n', "manifest id, renamed_from and what it keeps", re.M),
    _patch("src/plugins/{huddle,taskmanager}/cplug.json", r'"widgets": \["chat"\]', '"widgets": ["huddle.chat"]', "widget keeps its id (S9)"),
    _patch("src/plugins/{huddle,taskmanager}/cplug.json", r'^    "chat": \{$', '    "huddle.chat": {', "widget block keeps its id (S9)", re.M),
    _patch("src/plugins/{huddle,taskmanager}/carnivore.json", r'^  "id": "huddle",$', '  "id": "taskmanager",', "envelope id", re.M),
    _patch("src/plugins/{flow,reviewboard,tmdevtools}/cplug.json", r'"requires": \["huddle"\]', '"requires": ["taskmanager"]', "requires"),
    _patch("src/plugins/{flow,reviewboard,tmdevtools}/carnivore.json", r'"id": "huddle",(\s*"kind": "cplug")', r'"id": "taskmanager",\1',
           "envelope requires"),
    _patch("src/plugins/order.json", r'\["huddle",', '["taskmanager",', "ship order"),
    _patch("src/plugins/sdk/tool_families.py", r'\(\"huddle\", \"reviewboard\"', '("taskmanager", "reviewboard"', "tool family members"),
    _patch("src/plugins/host/swarm_default_migration.py", r'^SWARM_ID = "huddle"$', 'SWARM_ID = "taskmanager"', "Swarm default step", re.M),
    _patch("web/src/plugins/{huddle,taskmanager}/{index,popout}.ts", r"\bid: 'huddle'", "id: 'taskmanager'", "web plugin id"),
    _patch("web/src/plugins/{huddle,taskmanager}/chat/index.ts", r"\bname: 'chat'", "name: 'huddle.chat'", "web widget keeps its id (S9)"),
    _patch("web/src/lib/plugins-page/plugin-settings-link.ts", r"cplugId: 'huddle'", "cplugId: 'taskmanager'", "legacy settings link"),
    _patch("web/src/lib/plugins-page/plugin-settings-link.ts", r"'crate', 'huddle', 'save'", "'crate', 'save', 'taskmanager'", "settings plugins"),
    _patch("src/plugins/{huddle,taskmanager}/__init__.py", r'cplug="huddle"', 'cplug="taskmanager"', "start log names the plugin"),
    _patch("scripts/gate/tree_copy.py", r'^(NOT_REMOVABLE: [^\n]*\n(?:(?!\})[^\n]*\n)*?    )"huddle": ', r'\1"taskmanager": ',
           "release gate's not-removable table", re.M),
)


def is_excluded(path: str) -> bool:
    return any(rx.match(path) for rx in EXCLUDED_REGEXES)


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


def web_children(files: Iterable[str]) -> frozenset:
    del files
    return frozenset()


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
            if seg == OLD_NAME and tuple(stack) in MOVED_PARENTS:
                parts[idx] = NEW_NAME
                changed = True
            stack.append(seg)
    return "/".join(parts) if changed else None


SPECIFIER_RE = re.compile(r"""(?<=['"`(])(\.{1,2}/[^'"`()\s]*?\bhuddle\b[^'"`()\s]*)""")


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


def _bump(counts: Dict[str, int], name: str, hits: int) -> None:
    if hits:
        counts[name] = counts.get(name, 0) + hits


def apply_text_rules(path: str, text: str, counts: Dict[str, int], children: frozenset = frozenset()) -> str:
    del children
    is_spec_file = PurePosixPath(path).suffix in SPECIFIER_SUFFIXES
    old_dir = str(PurePosixPath(path).parent)
    out: List[str] = []
    for line in text.splitlines(keepends=True):
        for rule in TEXT_RULES:
            line, hits = rule.pattern.subn(rule.replacement, line)
            _bump(counts, rule.name, hits)
        if is_spec_file:
            line, hits = rewrite_specifiers(line, old_dir)
            _bump(counts, "relative import specifier", hits)
        out.append(line)
    result = "".join(out)
    for file_rx, rx, repl, why in FILE_PATCHES:
        if file_rx.match(path) or file_rx.match(new_path(path)):
            result, hits = rx.subn(repl, result)
            _bump(counts, f"patch: {why}", hits)
    return result


def leftover_hits(path: str, text: str, children: frozenset = frozenset()) -> List[str]:
    del children
    hits: List[str] = []
    is_spec_file = PurePosixPath(path).suffix in SPECIFIER_SUFFIXES
    for number, line in enumerate(text.splitlines(), start=1):
        hits += [f"line {number}: {r.name}" for r in TEXT_RULES if r.pattern.search(line)]
        if is_spec_file and rewrite_specifiers(line, str(PurePosixPath(old_path(path)).parent))[1]:
            hits.append(f"line {number}: relative import specifier")
    hits += [f"patch ({why})" for fr, rx, _, why in FILE_PATCHES if fr.match(path) and rx.search(text)]
    return hits


def invariant_counts(texts: Iterable[str]) -> Dict[str, int]:
    totals = {name: 0 for name, _ in INVARIANT_PATTERNS}
    for text in texts:
        for name, rx in INVARIANT_PATTERNS:
            totals[name] += len(rx.findall(text))
    return totals
