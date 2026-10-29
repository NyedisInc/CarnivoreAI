"""Read-only rule-file checks for the Scrooge recipe: sizes, estimated tokens and line overlap.

Nothing here writes. A rule file is opened for reading only, must be a regular file, and a symlink whose
target leaves the project folder and the home folder is never followed. Files over the stats store's own
``MAX_RULE_BYTES`` are reported ``oversize`` and not read.
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from src.core.stats.rules import MAX_RULE_BYTES, RULE_NAMES

GLOBAL_RULE_PATHS = (Path("~/.claude/CLAUDE.md"), Path("~/.codex/AGENTS.md"))
BYTES_PER_TOKEN = 4
_ALNUM = re.compile(r"[A-Za-z0-9]")
_SPACE = re.compile(r"\s+")


@dataclass
class RuleFile:

    label: str
    bytes: int
    est_tokens: int
    oversize: bool
    text: Optional[str]
    real_path: str


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def read_rule_file(path: Path, label: str, allowed_roots: Sequence[Path]) -> Optional[RuleFile]:
    """Read one rule file, or None when it is absent, not a regular file, unreadable or points outside the roots.

    Inputs: path (file to read), label (name to report), allowed_roots (resolved folders a symlink may land in).
    Output: RuleFile | None. Example: read_rule_file(Path("/p/CLAUDE.md"), "CLAUDE.md", [Path("/p")])
    """
    try:
        real = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not _inside(real, allowed_roots):
        return None
    try:
        with real.open("rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                return None
            if info.st_size > MAX_RULE_BYTES:
                return RuleFile(label, info.st_size, info.st_size // BYTES_PER_TOKEN, True, None, str(real))
            body = handle.read(MAX_RULE_BYTES + 1)
    except OSError:
        return None
    if len(body) > MAX_RULE_BYTES:
        return RuleFile(label, len(body), len(body) // BYTES_PER_TOKEN, True, None, str(real))
    return RuleFile(label, len(body), len(body) // BYTES_PER_TOKEN, False,
                    body.decode("utf-8", errors="replace"), str(real))


def read_project_rules(folder: Path) -> List[RuleFile]:
    roots = [folder.resolve(), Path.home().resolve()]
    found = (read_rule_file(folder / name, name, roots) for name in RULE_NAMES)
    return [item for item in found if item is not None]


def read_global_rules(paths: Sequence[Path] = GLOBAL_RULE_PATHS) -> List[RuleFile]:
    roots = [Path.home().resolve()]
    out = []
    for raw in paths:
        item = read_rule_file(raw.expanduser(), raw.as_posix(), roots)
        if item is not None:
            out.append(item)
    return out


def normalized_lines(text: str) -> set:
    lines = (_SPACE.sub(" ", raw.strip()).lower() for raw in text.splitlines())
    return {line for line in lines if _ALNUM.search(line)}


def _pair(a: RuleFile, b: RuleFile) -> Optional[Dict[str, object]]:
    if a.text is None or b.text is None or a.real_path == b.real_path:
        return None
    lines_a = normalized_lines(a.text)
    shared = len(lines_a & normalized_lines(b.text))
    if not shared:
        return None
    return {"a": a.label, "b": b.label, "shared_lines": shared,
            "shared_pct": round(100.0 * shared / len(lines_a), 1)}


def summarize_rules(project: Sequence[RuleFile], globals_: Sequence[RuleFile]) -> Dict[str, list]:
    rule_files = [{"path": f.label, "bytes": f.bytes, "est_tokens": f.est_tokens, "oversize": f.oversize}
                  for f in project]
    pairs = [(a, g) for a in project for g in globals_]
    by_label = {f.label: f for f in project}
    if "CLAUDE.md" in by_label and "AGENTS.md" in by_label:
        pairs.append((by_label["CLAUDE.md"], by_label["AGENTS.md"]))
    overlap = [row for row in (_pair(a, b) for a, b in pairs) if row is not None]
    return {"rule_files": rule_files, "overlap": overlap}
