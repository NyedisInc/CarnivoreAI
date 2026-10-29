
from __future__ import annotations

import json
import os
import re
from typing import Iterable, List, Optional, Set

import structlog

from src.core.claude_folder_trust import claude_json_path
from src.core.provider_ledger.credentials import claude_identity_path, is_default_claude_dir

logger = structlog.get_logger()

APPROVED_KEY = "hasClaudeMdExternalIncludesApproved"
MEMORY_NAMES = frozenset({"CLAUDE.md", "CLAUDE.local.md"})
SKIP_DIRS = frozenset({".git", "node_modules"})
MAX_FILES = 500
MAX_DIRS = 5000
MAX_BYTES = 1_000_000
MAX_DEPTH = 5
_IMPORT = re.compile(r"(?:^|\s)@(\S+)")


class _TooBig(Exception):
    pass


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _memory_files(root: str) -> List[str]:
    found: List[str] = []
    dirs = 0
    for base, names, files in os.walk(root, followlinks=False):
        dirs += 1
        names[:] = [n for n in names if n not in SKIP_DIRS]
        rel = os.path.relpath(base, root) + os.sep
        in_rules = (os.sep + ".claude" + os.sep + "rules" + os.sep) in (os.sep + rel)
        found += [os.path.join(base, f) for f in files if f in MEMORY_NAMES or (in_rules and f.endswith(".md"))]
        if dirs > MAX_DIRS or len(found) > MAX_FILES:
            raise _TooBig()
    return found


def _import_targets(text: str, base_dir: str) -> List[str]:
    out: List[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        for raw in _IMPORT.findall(re.sub(r"`[^`]*`", "", line)):
            raw = raw.rstrip(".,;:)!?\"'")
            if raw:
                out.append(os.path.normpath(os.path.join(base_dir, os.path.expanduser(raw))))
    return out


def own_files_import_outside(folder: str) -> bool:
    root = os.path.realpath(folder)
    try:
        queue = [(f, 0) for f in _memory_files(root)]
    except (_TooBig, OSError):
        return True
    seen: Set[str] = set()
    while queue:
        path, depth = queue.pop()
        real = os.path.realpath(path)
        if not _inside(real, root):
            return True  # resolves outside
        if real in seen or not os.path.isfile(real):
            continue
        seen.add(real)
        try:
            if os.path.getsize(real) > MAX_BYTES:
                return True
            with open(real, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return True
        for target in _import_targets(text, os.path.dirname(real)):
            if not _inside(os.path.realpath(target), root):
                return True
            if depth < MAX_DEPTH:
                queue.append((target, depth + 1))
    return False


def _approved_in(path, folder: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            projects = json.load(fh).get("projects")
    except (OSError, UnicodeDecodeError, ValueError, AttributeError) as exc:
        logger.info("pack_imports_unreadable", error=type(exc).__name__)
        return False
    if not isinstance(projects, dict):
        return False
    return any(isinstance(projects.get(k), dict) and projects[k].get(APPROVED_KEY) is True for k in {folder, os.path.realpath(folder)})


def source_imports_ok(folder: Optional[str], profile_dirs: Iterable[Optional[str]]) -> bool:
    if not folder or not os.path.isdir(folder):
        return False
    if not own_files_import_outside(folder):
        return True
    for profile in set(profile_dirs) or {None}:
        if profile == "":
            return False
        path = claude_json_path() if profile is None or is_default_claude_dir(profile) else claude_identity_path(profile)
        if not _approved_in(path, folder):
            return False
    return True
