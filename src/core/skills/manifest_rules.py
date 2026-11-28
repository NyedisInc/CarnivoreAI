
from __future__ import annotations

import json
import tomllib
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


def _is_schema_two(value: object) -> bool:
    return type(value) is int and value == 2


def _cplug_manifest_conflict(folder: Path) -> Optional[str]:
    cplug_name = kinds.MANIFEST_FOR[kinds.KIND_CPLUG]
    has_cplug = (folder / cplug_name).is_file()
    has_toml = (folder / kinds.CPLUG_TOML_MANIFEST).is_file()
    json_path = folder / kinds.CPLUG_JSON_MANIFEST
    has_json = json_path.is_file()

    if has_toml and has_cplug:
        return f"{kinds.CPLUG_TOML_MANIFEST} cannot coexist with {cplug_name}"
    if has_toml and has_json:
        return f"both {kinds.CPLUG_TOML_MANIFEST} and {kinds.CPLUG_JSON_MANIFEST} exist; keep one"
    if has_json:
        try:
            if json_path.stat().st_size > MAX_MANIFEST_BYTES:
                return f"{kinds.CPLUG_JSON_MANIFEST} is larger than {MAX_MANIFEST_BYTES} bytes"
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            if not has_cplug and not has_toml:
                return f"{kinds.CPLUG_JSON_MANIFEST} could not be read: {exc}"
            return None
        except json.JSONDecodeError as exc:
            if not has_cplug and not has_toml:
                return f"{cplug_name} is missing from the folder ({kinds.CPLUG_JSON_MANIFEST} is not valid JSON: {exc})"
            return None
        if not isinstance(raw, dict):
            if not has_cplug and not has_toml:
                return f"{kinds.CPLUG_JSON_MANIFEST} is not a JSON object"
            return None
        is_v2 = _is_schema_two(raw.get("schema"))
        if has_cplug and is_v2:
            return f"v2 {kinds.CPLUG_JSON_MANIFEST} cannot coexist with {cplug_name}"
        if not has_cplug and not has_toml and not is_v2:
            return f"{cplug_name} is missing from the folder (and {kinds.CPLUG_JSON_MANIFEST} is not schema = 2)"
    return None


def _read_manifest_object(kind: str, folder: Path) -> tuple[Optional[dict], Optional[str]]:
    if kind == kinds.KIND_CPLUG:
        conflict = _cplug_manifest_conflict(folder)
        if conflict is not None:
            return None, conflict

    name = kinds.resolve_manifest_name(kind, folder)
    path = folder / name
    try:
        if not path.is_file():
            return None, f"{name} is missing from the folder"
        size = path.stat().st_size
        if size > MAX_MANIFEST_BYTES:
            return None, f"{name} is larger than {MAX_MANIFEST_BYTES} bytes"
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{name} could not be read: {exc}"

    if name.endswith(".toml"):
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            return None, f"{name} is not valid TOML: {exc}"
        if not isinstance(raw, dict):
            return None, f"{name} is not a TOML table"
        if kind == kinds.KIND_CPLUG and not _is_schema_two(raw.get("schema")):
            return None, f"{name} must declare schema = 2"
        return raw, None

    try:
        raw = json.loads(text)
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
