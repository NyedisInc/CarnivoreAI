
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from src.core.notifications import kind_specs, types

BLOCK = "notification_routing"
DOC_VERSION = 1
TOMBSTONE_TTL_SECONDS = 30 * 24 * 3600
COL_SCREEN = "screen"
EXTRAS: Tuple[str, ...] = ("away", "quiet", "reminder", "projects", "details")
LOCAL_PREFIX = "local/"

KIND_DEST = "dest"
KIND_TICK = "tick"
KIND_EXTRA = "extra"
KIND_DEFAULT = "default"
KIND_MUTE = "mute"
KIND_LOCAL = "local"

Version = Tuple[int, str]
Entry = Dict[str, Any]


@dataclass(frozen=True)
class ParsedPath:

    kind: str
    dest: Optional[str] = None
    type_id: Optional[str] = None
    col: Optional[str] = None
    extra: Optional[str] = None
    name: Optional[str] = None


def _check_dest(dest: str) -> str:
    if kind_specs.is_destination_id(dest) or kind_specs.is_push_destination_id(dest):
        return dest
    raise ValueError(f"not a destination id: {dest!r}")


def _check_type(type_id: str) -> str:
    if not types.is_registered(type_id):
        raise ValueError(f"not a notification type: {type_id!r}")
    return type_id


def dest_path(dest: str) -> str:
    return f"{KIND_DEST}/{_check_dest(dest)}"


def tick_path(col: str, type_id: str) -> str:
    if col != COL_SCREEN:
        _check_dest(col)
    return f"{KIND_TICK}/{col}/{_check_type(type_id)}"


def extra_path(dest: str, extra: str) -> str:
    if extra not in EXTRAS:
        raise ValueError(f"not an extra: {extra!r}")
    return f"{KIND_EXTRA}/{_check_dest(dest)}/{extra}"


def default_path(type_id: str) -> str:
    return f"{KIND_DEFAULT}/{_check_type(type_id)}"


def mute_path(type_id: str) -> str:
    return f"{KIND_MUTE}/{_check_type(type_id)}"


def local_key(name: str) -> str:
    if not name or "/" in name:
        raise ValueError(f"not a local key name: {name!r}")
    return LOCAL_PREFIX + name


def parse_path(path: str) -> ParsedPath:
    if not isinstance(path, str):
        raise ValueError("path must be a string")
    head, _, rest = path.partition("/")
    if head == KIND_DEST:
        return ParsedPath(KIND_DEST, dest=_check_dest(rest))
    if head == KIND_DEFAULT:
        return ParsedPath(KIND_DEFAULT, type_id=_check_type(rest))
    if head == KIND_MUTE:
        return ParsedPath(KIND_MUTE, type_id=_check_type(rest))
    if head == KIND_TICK:
        col, _, type_id = rest.partition("/")
        if col != COL_SCREEN:
            _check_dest(col)
        return ParsedPath(KIND_TICK, col=col, type_id=_check_type(type_id))
    if head == KIND_EXTRA:
        dest, _, extra = rest.partition("/")
        if extra not in EXTRAS:
            raise ValueError(f"not an extra: {extra!r}")
        return ParsedPath(KIND_EXTRA, dest=_check_dest(dest), extra=extra)
    if head == KIND_LOCAL and rest and "/" not in rest:
        return ParsedPath(KIND_LOCAL, name=rest)
    raise ValueError(f"not a settings path: {path!r}")


def is_local_only(path: str) -> bool:
    return isinstance(path, str) and path.startswith(LOCAL_PREFIX)


def empty_doc() -> Dict[str, Any]:
    return {"v": DOC_VERSION, "global": {}, "local": {}}


def parse_version(raw: Any) -> Version:
    if (
        isinstance(raw, (list, tuple)) and len(raw) == 2
        and isinstance(raw[0], int) and not isinstance(raw[0], bool) and raw[0] >= 0
        and isinstance(raw[1], str) and raw[1]
    ):
        return (raw[0], raw[1])
    raise ValueError(f"not a version: {raw!r}")


def compare_versions(a: Version, b: Version) -> int:
    return (a > b) - (a < b)


def is_tombstone(entry: Mapping[str, Any]) -> bool:
    return "tomb" in entry


def _canon(entry: Mapping[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


def pick_winner(a: Entry, b: Entry) -> Entry:
    order = compare_versions(parse_version(a["ver"]), parse_version(b["ver"]))
    if order != 0:
        return a if order > 0 else b
    return a if _canon(a) >= _canon(b) else b


def merge_global(mine: Mapping[str, Entry], theirs: Mapping[str, Entry]) -> Dict[str, Entry]:
    merged: Dict[str, Entry] = {}
    for path in set(mine) | set(theirs):
        a, b = mine.get(path), theirs.get(path)
        merged[path] = copy.deepcopy(a if b is None else b if a is None else pick_winner(a, b))
    return merged


def prune_tombstones(global_map: Mapping[str, Entry], now: float) -> Dict[str, Entry]:
    return {
        p: copy.deepcopy(e) for p, e in global_map.items()
        if not (is_tombstone(e) and now - float(e["tomb"]) > TOMBSTONE_TTL_SECONDS)
    }


def _next_counter(doc: Mapping[str, Any], path: str) -> int:
    entry = doc["global"].get(path)
    return (parse_version(entry["ver"])[0] if entry else 0) + 1


def set_global(doc: Mapping[str, Any], path: str, val: Any, install_id: str) -> Dict[str, Any]:
    parse_path(path)
    if is_local_only(path):
        raise ValueError("a local-only key cannot be global")
    out = copy.deepcopy(dict(doc))
    out["global"][path] = {"val": val, "ver": [_next_counter(doc, path), install_id]}
    return out


def delete_global(doc: Mapping[str, Any], path: str, install_id: str, now: float) -> Dict[str, Any]:
    parse_path(path)
    out = copy.deepcopy(dict(doc))
    out["global"][path] = {"tomb": now, "ver": [_next_counter(doc, path), install_id]}
    return out


def set_local(doc: Mapping[str, Any], path: str, val: Any) -> Dict[str, Any]:
    parse_path(path)
    out = copy.deepcopy(dict(doc))
    out["local"][path] = val
    return out


def clear_local(doc: Mapping[str, Any], path: str) -> Dict[str, Any]:
    out = copy.deepcopy(dict(doc))
    out["local"].pop(path, None)
    return out


def is_pinned(doc: Mapping[str, Any], path: str) -> bool:
    return path in doc["local"]


def effective_source(doc: Mapping[str, Any], path: str) -> str:
    if path in doc["local"]:
        return "local"
    entry = doc["global"].get(path)
    if entry is not None and not is_tombstone(entry):
        return "global"
    return "absent"


def effective_value(doc: Mapping[str, Any], path: str, default: Any = None) -> Any:
    source = effective_source(doc, path)
    if source == "local":
        return doc["local"][path]
    if source == "global":
        return doc["global"][path]["val"]
    return default
