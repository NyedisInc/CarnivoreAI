
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from src.core.skills import kinds
from src.core.skills.validate_types import ArchiveRefused
from src.models.catalog import CatalogItem
from src.models.catalog_names import is_first_party_publisher

THEME_IMAGE_SUFFIXES = (".webp", ".png", ".jpg")

THEME_METADATA_FILES = frozenset({"carnivore.json", "LICENSE", "LICENSE.md"})

FIRST_PARTY_FILES = ("effects.js", "effects-base.js", "mascot.svg")

THEME_DATA_KEYS = frozenset(
    {"id", "name", "description", "author", "version", "cssVars", "xterm", "background", "characters"}
)

FIRST_PARTY_KEYS = frozenset({"effects", "mascot"})

EFFECTS_BASE = "./effects-base.js"

_STATIC_IMPORT_RE = re.compile(r"""\b(?:import|export)\b[^;"'`]*?\bfrom\s*(["'])(.*?)\1|\bimport\s*(["'])(.*?)\3""", re.S)
_DYNAMIC_IMPORT_RE = re.compile(r"""\bimport\s*\(\s*(?:(["'])(.*?)\1\s*\))?""", re.S)

SCRIPTS_NOT_SUPPORTED = "scripts_not_supported"


def is_first_party_item(item: CatalogItem) -> bool:
    return item.kind == kinds.KIND_THEME and is_first_party_publisher(item.publisher)


def _import_reason(root: Path, name: str) -> Optional[str]:
    try:
        text = (root / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return f"{name} (unreadable)"
    specs = [m.group(2) or m.group(4) for m in _STATIC_IMPORT_RE.finditer(text)]
    specs += [m.group(2) if m.group(2) is not None else "<dynamic>" for m in _DYNAMIC_IMPORT_RE.finditer(text)]
    for spec in specs:
        if spec != EFFECTS_BASE or not (root / "effects-base.js").is_file():
            return f"{name} imports {spec[:60]!r}"
    return None


def _code_reason(root: Path, first_party: bool) -> Optional[str]:
    manifest_name = kinds.manifest_name(kinds.KIND_THEME)
    allowed_files = THEME_METADATA_FILES | set(FIRST_PARTY_FILES) if first_party else THEME_METADATA_FILES
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_symlink():
            return str(rel)
        if not path.is_file():
            continue
        name = path.name
        if len(rel.parts) == 1 and (
            name == manifest_name or name in allowed_files or name.lower().endswith(THEME_IMAGE_SUFFIXES)
        ):
            continue
        return str(rel)
    manifest = root / manifest_name
    try:
        raw: Any = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "theme.json (unreadable)"
    if not isinstance(raw, dict):
        return "theme.json (not an object)"
    allowed_keys = THEME_DATA_KEYS | FIRST_PARTY_KEYS if first_party else THEME_DATA_KEYS
    for key in raw:
        if key not in allowed_keys:
            return f"theme.json key {str(key)[:40]!r}"
    if first_party:
        for name in ("effects.js", "effects-base.js"):
            if (root / name).is_file():
                reason = _import_reason(root, name)
                if reason is not None:
                    return reason
    return None


def refuse_theme_code(item: CatalogItem, staged_path: Path) -> None:
    if item.kind != kinds.KIND_THEME:
        return
    reason = _code_reason(staged_path, is_first_party_item(item))
    if reason is not None:
        raise ArchiveRefused(
            SCRIPTS_NOT_SUPPORTED,
            f"a theme carries theme.json and images only, plus first-party scripts ({reason})",
        )
