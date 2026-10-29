
from __future__ import annotations

import os
from typing import Optional, Sequence, Tuple

SCRATCH_PREFIXES: Tuple[str, ...] = ("/private/tmp", "/tmp", "/var/folders")

TITLE_MAX = 80


def canonical(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        return os.path.realpath(path)
    except OSError:
        return None


def is_scratch(path: Optional[str]) -> bool:
    if not path:
        return False
    for candidate in (path, canonical(path) or path):
        for prefix in SCRATCH_PREFIXES:
            if candidate == prefix or candidate.startswith(prefix + "/"):
                return True
    return False


def git_top_level(path: str, *, home: Optional[str] = None) -> Optional[str]:
    ceiling = canonical(home or os.path.expanduser("~")) or "/"
    current = path
    while True:
        try:
            if os.path.exists(os.path.join(current, ".git")):
                return current
        except OSError:
            return None
        if current == ceiling or current == "/":
            return None
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def truncate_title(text: Optional[str], limit: int = TITLE_MAX) -> Optional[str]:
    if not text:
        return None
    flat = " ".join(str(text).split())
    if not flat:
        return None
    if len(flat) <= limit:
        return flat
    window = flat[: limit - 3]
    cut = window.rfind(" ")
    if cut > 0:
        window = window[:cut]
    return window.rstrip(" ,.;:-") + "..."


def match_project(
    working_dir: str, project_roots: Sequence[str]
) -> Optional[str]:
    best: Optional[str] = None
    for root in project_roots:
        if working_dir == root or working_dir.startswith(root.rstrip("/") + "/"):
            if best is None or len(root) > len(best):
                best = root
    return best
