
from __future__ import annotations

import unicodedata
from typing import Iterable, Optional

from src.core.skills.roots import unsafe_name_reason

FAMILIES: tuple[str, ...] = ("claude", "codex")

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_SKILL_BYTES = 10 * 1024 * 1024
MAX_SKILL_FILES = 500
MAX_SET_BYTES = 100 * 1024 * 1024
MAX_SET_FILES = 5000
MAX_PATH_BYTES = 255
MAX_DEPTH = 12
MAX_SKILLS = 400
MAX_INVENTORY_ROWS = 2000
MAX_NAME_BYTES = 120
MAX_DOC_BYTES = 60 * 1024

MACHINE_LOCAL_NAMES = frozenset({"node_modules", ".venv", "venv", "__pycache__", ".git"})
IGNORED_BASENAMES = frozenset({".DS_Store", ".carnivore-skill.json"})
RESERVED_NAMES = frozenset({"synced"})

REASON_TOO_LARGE = "too large"
REASON_LINK_INSIDE = "link inside"
REASON_HARD_LINK = "hard link inside"
REASON_MISSING_ON_ALPHA = "missing on alpha"


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def fold_key(text: str) -> str:
    return nfc(text).casefold()


def is_machine_local_file(basename: str) -> bool:
    return basename.endswith(".pyc")


def has_control_chars(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def required_skill_names() -> frozenset[str]:
    from src.core.skills.required import REQUIRED_SKILLS

    return frozenset(s.folder for s in REQUIRED_SKILLS)


def skill_name_problem(name: str, required: Optional[Iterable[str]] = None) -> Optional[str]:
    reason = unsafe_name_reason(name)
    if reason is not None:
        return reason
    if "/" in name:
        return "name is a path"
    if has_control_chars(name):
        return "name holds a control character"
    if len(name.encode("utf-8")) > MAX_NAME_BYTES:
        return "name too long"
    if name in RESERVED_NAMES or name in MACHINE_LOCAL_NAMES:
        return "reserved name"
    banned = required_skill_names() if required is None else frozenset(required)
    if nfc(name) in banned:
        return "bundled skill"
    return None


def path_problem(path: str) -> Optional[str]:
    if not path or path.startswith("/") or "\\" in path:
        return "path not relative"
    if has_control_chars(path):
        return "path holds a control character"
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return "path escapes"
    if any(p in MACHINE_LOCAL_NAMES for p in parts):
        return "machine-local component"
    if len(parts) > MAX_DEPTH:
        return "path too deep"
    if len(path.encode("utf-8")) > MAX_PATH_BYTES:
        return "path too long"
    return None


def collision(paths: Iterable[str]) -> Optional[str]:
    seen: dict[str, str] = {}
    for path in paths:
        key = fold_key(path)
        if key in seen and seen[key] != path:
            return f"paths differ only by case: {path}"
        seen[key] = path
    return None
