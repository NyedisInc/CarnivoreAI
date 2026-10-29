
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

import structlog

from src.core.skills import kinds
from src.core.skills.plugin_safe_subset import plugin_declares_code

logger = structlog.get_logger()

SHAPE_TEXT = "text"

SHAPE_JSON = "json"

MANIFEST_SHAPE_FOR: Mapping[str, str] = {
    kinds.KIND_SKILL: SHAPE_TEXT,
    kinds.KIND_THEME: SHAPE_JSON,
    kinds.KIND_PLUGIN: SHAPE_JSON,
    kinds.KIND_LOADOUT: SHAPE_JSON,
    kinds.KIND_MOD: SHAPE_JSON,
    kinds.KIND_CPLUG: SHAPE_JSON,
}

IDENTITY_KEY_FOR: Mapping[str, Optional[str]] = {
    kinds.KIND_SKILL: None,
    kinds.KIND_THEME: "id",
    kinds.KIND_PLUGIN: None,
    kinds.KIND_LOADOUT: None,
    kinds.KIND_MOD: None,
    kinds.KIND_CPLUG: None,
}

SCRIPT_KEY_FOR: Mapping[str, Optional[str]] = {
    kinds.KIND_SKILL: None,
    kinds.KIND_THEME: "effects",
    kinds.KIND_PLUGIN: None,
    kinds.KIND_LOADOUT: None,
    kinds.KIND_MOD: None,
    kinds.KIND_CPLUG: None,
}

MAX_MANIFEST_BYTES = 1024 * 1024


def manifest_shape(kind: str) -> str:
    if kind not in MANIFEST_SHAPE_FOR:
        raise ValueError(
            f"unknown install kind {kind!r}; known kinds are "
            f"{sorted(MANIFEST_SHAPE_FOR)}"
        )
    return MANIFEST_SHAPE_FOR[kind]


def identity_key(kind: str) -> Optional[str]:
    if kind not in IDENTITY_KEY_FOR:
        raise ValueError(
            f"unknown install kind {kind!r}; known kinds are "
            f"{sorted(IDENTITY_KEY_FOR)}"
        )
    return IDENTITY_KEY_FOR[kind]


def script_key(kind: str) -> Optional[str]:
    if kind not in SCRIPT_KEY_FOR:
        raise ValueError(
            f"unknown install kind {kind!r}; known kinds are "
            f"{sorted(SCRIPT_KEY_FOR)}"
        )
    return SCRIPT_KEY_FOR[kind]


def _read_manifest_object(kind: str, folder: Path) -> tuple[Optional[dict], Optional[str]]:
    name = kinds.manifest_name(kind)
    path = folder / name
    try:
        if not path.is_file():
            return None, f"{name} is missing from the folder"
        size = path.stat().st_size
        if size > MAX_MANIFEST_BYTES:
            return None, f"{name} is larger than {MAX_MANIFEST_BYTES} bytes"
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{name} could not be read: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"{name} is not valid JSON: {exc}"
    if not isinstance(raw, dict):
        return None, f"{name} is not a JSON object"
    return raw, None


def check_manifest(kind: str, folder: Path, *, expected_id: str) -> Optional[str]:
    if manifest_shape(kind) == SHAPE_TEXT:
        return None

    raw, refusal = _read_manifest_object(kind, folder)
    if refusal is not None:
        return refusal

    key = identity_key(kind)
    if key is None:
        return None

    declared = raw.get(key)
    if declared != expected_id:
        return (
            f"{kinds.manifest_name(kind)} declares {key} {declared!r} but the "
            f"folder is installed as {expected_id!r}; the two must match or "
            f"the {kind} is installed and never listed"
        )
    return None


def declares_script(kind: str, folder: Path) -> bool:
    key = script_key(kind)
    if key is None and kind != kinds.KIND_PLUGIN:
        return False

    raw, refusal = _read_manifest_object(kind, folder)
    if refusal is not None:
        logger.warning(
            "manifest_script_declaration_unreadable",
            kind=kind,
            folder=str(folder),
            reason=refusal,
            outcome="treated as script bearing",
        )
        return True

    if kind == kinds.KIND_PLUGIN:
        return plugin_declares_code(raw, folder)
    declared = raw.get(key)
    return isinstance(declared, str) and bool(declared.strip())
