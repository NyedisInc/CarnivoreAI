
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from src.core.skills import kinds
from src.plugins.host.sideload import SideloadRefused
from src.plugins.sdk.manifest_v2 import JSON_FILE, MAX_MANIFEST_BYTES, TOML_FILE

ROOT_MANIFESTS: Tuple[Tuple[str, str], ...] = (
    (kinds.KIND_CPLUG, "cplug.json"),
    (kinds.KIND_THEME, "theme.json"),
    (kinds.KIND_SKILL, "SKILL.md"),
    (kinds.KIND_PLUGIN, ".claude-plugin/plugin.json"),
)
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FRONT_NAME_RE = re.compile(r"^name:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)
_MAX_READ = 64 * 1024


def _is_file(path: Path) -> bool:
    return os.path.isfile(path) and not os.path.islink(path)


def _read_json(path: Path, *, max_bytes: int = _MAX_READ) -> Optional[dict]:
    try:
        if path.stat().st_size > max_bytes:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_mod(source: Path) -> bool:
    hooks = _read_json(source / "hooks" / "hooks.json")
    return bool(hooks) and "modules" in hooks


def detect(source: Path) -> str:
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise SideloadRefused("source_missing", "give the absolute path of a folder (not a link)", 422)
    found: List[str] = [kind for kind, rel in ROOT_MANIFESTS if _is_file(source / rel)]
    has_toml = _is_file(source / TOML_FILE)
    has_json = _is_file(source / JSON_FILE)
    if has_toml and has_json:
        raise SideloadRefused("kind_ambiguous", "the folder holds both carnivore.toml and carnivore.json; keep one manifest", 422)
    json_path = source / JSON_FILE
    if has_json:
        try:
            json_size = json_path.stat().st_size
        except OSError as exc:
            raise SideloadRefused("manifest_invalid", f"{JSON_FILE} could not be read ({type(exc).__name__})", 422) from exc
        if json_size > MAX_MANIFEST_BYTES:
            raise SideloadRefused("manifest_invalid", f"{JSON_FILE} exceeds {MAX_MANIFEST_BYTES} bytes", 422)
    record = _read_json(json_path, max_bytes=MAX_MANIFEST_BYTES) if has_json else None
    if has_json and record is None and kinds.KIND_CPLUG in found:
        raise SideloadRefused("manifest_invalid", f"{JSON_FILE} is unreadable or not a JSON object", 422)
    is_v2_json = bool(record and type(record.get("schema")) is int and record.get("schema") == 2)
    is_authored_v1 = bool(record and "sidecar" in record and not is_v2_json)
    if has_toml:
        found.append(kinds.KIND_CPLUG)
    elif is_v2_json:
        found.append(kinds.KIND_CPLUG)
    elif is_authored_v1 and kinds.KIND_CPLUG not in found:
        found.append(kinds.KIND_CPLUG)
    if len(found) > 1:
        raise SideloadRefused("kind_ambiguous", f"the folder holds more than one plugin manifest ({', '.join(sorted(found))}); sideload one kind at a time", 422)
    if found == [kinds.KIND_PLUGIN] and is_mod(source):
        raise SideloadRefused("kind_unsupported_mod", "this is a Claude Code mod; mods carry their own consent and are not sideloaded here", 422)
    if found:
        return found[0]
    if record and record.get("kind") == "widget":
        raise SideloadRefused("kind_unsupported", "a widget is not loaded on its own: a widget comes inside a plugin, so put it in a plugin folder with a cplug.json that declares it and sideload that folder", 422)
    raise SideloadRefused("kind_unknown", "the folder has none of carnivore.toml, carnivore.json (schema 2), cplug.json, theme.json, SKILL.md or .claude-plugin/plugin.json", 422)


def name_for(kind: str, source: Path, given: Optional[str]) -> str:
    name = given if given is not None else _declared(kind, source)
    if not isinstance(name, str) or not NAME_RE.match(name):
        code, status = ("name_invalid", 409) if given is not None else ("manifest_invalid", 422)
        raise SideloadRefused(code, f"an install name is a plain file name matching {NAME_RE.pattern}", status)
    return name


def _declared(kind: str, source: Path) -> Optional[str]:
    if kind == kinds.KIND_THEME:
        return (_read_json(source / "theme.json") or {}).get("id")
    if kind == kinds.KIND_PLUGIN:
        return (_read_json(source / ".claude-plugin" / "plugin.json") or {}).get("name")
    try:
        with (source / "SKILL.md").open("rb") as handle:
            head = handle.read(_MAX_READ).decode("utf-8", "replace")
    except OSError:
        return None
    front = head.split("---", 2)[1] if head.startswith("---") and head.count("---") >= 2 else ""
    match = _FRONT_NAME_RE.search(front)
    return match.group(1) if match else source.name
