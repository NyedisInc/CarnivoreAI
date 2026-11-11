
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.catalog.engines_range import ENGINES_KEY, EngineRangeError, engines_range

SIDECAR_KEY = "sidecar"
CARNIVORE_FILE = "carnivore.json"
CPLUG_FILE = "cplug.json"
FIELD_FLOOR = "1.16.2"
PAGE_TOPICS_FLOOR = "1.16.6"
TIER_LOCAL, TIER_CATALOG = "local", "catalog"

ENVELOPE_KEYS = frozenset({
    "api_version", "author", "data", "description", "id", "keywords", "kind", "license", "links", "min_app_version",
    "min_harness_version", "name", "owns", "permissions", "requires", "scope", "tier", "upstream", "version"})
CPLUG_KEYS = frozenset({"default_enabled", "icon", "kind", "network_hosts", "owns", "requires", "runtime", "scope"})
NEWER_KEYS = frozenset({"page", "topics"})
EMIT_KEYS = ENVELOPE_KEYS | CPLUG_KEYS | NEWER_KEYS
AUTHORED_KEYS = EMIT_KEYS | {SIDECAR_KEY, ENGINES_KEY}
CPLUG_JSON_KEYS = frozenset({
    "schema", "id", "name", "description", "version", "entry", "tools", "permissions", "default_enabled", "network_hosts",
    "lan_hosts", "secrets", "routes", "subscriptions", "views", "trust", "preview"})
SHARED_FIELDS = ("id", "name", "description", "version", "default_enabled", "network_hosts", "permissions")
SIDECAR_KEYS = CPLUG_JSON_KEYS - set(SHARED_FIELDS) - {"schema"}
_CARNIVORE_ORDER = ("kind", "id", "name", "description", "version", "api_version", "min_app_version", "author", "license", "tier",
                    "scope", "icon", "default_enabled", "runtime", "network_hosts", "permissions", "requires", "owns", "data",
                    "page", "topics", "keywords", "links", "upstream", "min_harness_version")
_CPLUG_ORDER = ("schema", "id", "name", "description", "version", "entry", "tools", "permissions", "default_enabled", "network_hosts",
                "lan_hosts", "secrets", "routes", "subscriptions", "views", "trust", "preview")


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class Packed:

    carnivore: Dict[str, Any]
    cplug: Dict[str, Any]
    notes: Tuple[str, ...] = ()


def is_authored(doc: Mapping[str, Any]) -> bool:
    return isinstance(doc, Mapping) and SIDECAR_KEY in doc


def vtuple(text: str) -> Tuple[int, ...]:
    try:
        return tuple(int(p) for p in str(text).split("."))
    except ValueError as exc:
        raise PackError(f"min_app_version {text!r} is not a dotted number") from exc


def _ordered(doc: Mapping[str, Any], order: Tuple[str, ...]) -> Dict[str, Any]:
    out = {k: doc[k] for k in order if k in doc}
    out.update({k: v for k, v in doc.items() if k not in out})
    return out


def _name_of(item_id: Any) -> str:
    if not isinstance(item_id, str) or not item_id:
        raise PackError("id is required (the plugin name, for example clock)")
    return item_id.rpartition("/")[2]


def _permission_names(permissions: Any) -> List[str]:
    if permissions is None:
        return []
    if not isinstance(permissions, list) or not all(isinstance(p, dict) and isinstance(p.get("name"), str) for p in permissions):
        raise PackError("permissions must be a list of {name, reason} objects")
    return [p["name"] for p in permissions]


def _check_keys(authored: Mapping[str, Any]) -> Dict[str, Any]:
    unknown = sorted(set(authored) - AUTHORED_KEYS)
    if unknown:
        raise PackError(f"carnivore.json may not carry {', '.join(unknown)}: apps in the field refuse unknown keys (put runtime settings under sidecar)")
    side = authored.get(SIDECAR_KEY)
    if not isinstance(side, dict):
        raise PackError("sidecar must be an object holding entry, tools, routes and the other cplug.json fields")
    stray = sorted(set(side) - SIDECAR_KEYS - {"permissions"})
    if stray:
        shared = [k for k in stray if k in SHARED_FIELDS or k == "schema"]
        raise PackError(f"sidecar may not carry {', '.join(stray)}" + (f" ({', '.join(shared)} is written once, at the top level)" if shared else ""))
    if not isinstance(side.get("entry"), str) or not side["entry"].endswith(".py"):
        raise PackError("sidecar.entry must name a .py file in the folder")
    return side


def _identity(authored: Mapping[str, Any], publisher: Optional[str]) -> Tuple[str, str, str]:
    name = _name_of(authored.get("id"))
    if publisher:
        return name, f"{publisher}/{name}", TIER_CATALOG
    declared = authored.get("id")
    if "/" in declared and authored.get("tier") == TIER_CATALOG:
        return name, declared, TIER_CATALOG
    return name, f"local/{name}", TIER_LOCAL


def _min_app(authored: Mapping[str, Any], notes: List[str]) -> str:
    need = str(authored.get("min_app_version") or FIELD_FLOOR)
    vtuple(need)
    try:
        engine = engines_range(dict(authored))
    except EngineRangeError as exc:
        raise PackError(str(exc)) from exc
    if engine is not None:
        if vtuple(engine.lower_text) > vtuple(need):
            notes.append(f"min_app_version raised from {need} to {engine.lower_text}: the lower bound of engines.carnivore")
            need = engine.lower_text
        if engine.has_upper:
            notes.append("engines.carnivore has an upper bound (an exact version is one); apps cannot enforce it, so only its lower bound is packed")
    if (authored.get("page") is not None or authored.get("topics") is not None) and vtuple(need) < vtuple(PAGE_TOPICS_FLOOR):
        notes.append(f"min_app_version raised from {need} to {PAGE_TOPICS_FLOOR}: page and topics are read from {PAGE_TOPICS_FLOOR}")
        need = PAGE_TOPICS_FLOOR
    return need


def _cplug_json(authored: Mapping[str, Any], side: Mapping[str, Any], name: str) -> Dict[str, Any]:
    names = _permission_names(authored.get("permissions"))
    if "permissions" in side and (side["permissions"] != {"app": names}):
        raise PackError("sidecar.permissions must equal the names in permissions (write them once, at the top level)")
    doc: Dict[str, Any] = {"schema": 1, "id": name, "name": authored.get("name"), "version": authored.get("version"),
                           "permissions": {"app": names}, "default_enabled": bool(authored.get("default_enabled", False))}
    if authored.get("description") is not None:
        doc["description"] = authored["description"]
    if authored.get("network_hosts") is not None:
        doc["network_hosts"] = authored["network_hosts"]
    doc.update({k: v for k, v in side.items() if k != "permissions"})
    doc.setdefault("tools", [])
    return _ordered(doc, _CPLUG_ORDER)


def _carnivore_json(authored: Mapping[str, Any], side: Mapping[str, Any], ident: Tuple[str, str, str], need: str) -> Dict[str, Any]:
    name, item_id, tier = ident
    doc = {k: v for k, v in authored.items() if k in EMIT_KEYS}
    for key in ("name", "version", "author"):
        if not isinstance(doc.get(key), str) or not doc[key]:
            raise PackError(f"{key} is required")
    doc.update(kind="cplug", id=item_id, tier=tier, min_app_version=need)
    for key, value in (("api_version", 1), ("scope", ["global"]), ("icon", "plug"), ("default_enabled", False),
                       ("permissions", []), ("owns", {}), ("data", [])):
        doc.setdefault(key, value)
    runtime = {"kind": "process", "language": "python", "entry": side["entry"]}
    doc["runtime"] = {**runtime, **(doc.get("runtime") or {})}
    doc.setdefault("network_hosts", [])
    return _ordered(doc, _CARNIVORE_ORDER)


def pack_manifest(authored: Mapping[str, Any], publisher: Optional[str] = None) -> Packed:
    if not is_authored(authored):
        raise PackError("this manifest has no sidecar key; use check_pair for a hand-written pair")
    side = _check_keys(authored)
    notes: List[str] = []
    ident = _identity(authored, publisher)
    need = _min_app(authored, notes)
    cplug = _cplug_json(authored, side, ident[0])
    carnivore = _carnivore_json(authored, side, ident, need)
    return Packed(carnivore, cplug, tuple(notes))


def check_pair(carnivore: Mapping[str, Any], cplug: Mapping[str, Any]) -> Packed:
    unknown = sorted(set(carnivore) - EMIT_KEYS)
    if unknown:
        raise PackError(f"carnivore.json may not carry {', '.join(unknown)}")
    if _name_of(carnivore.get("id")) != cplug.get("id"):
        raise PackError("the id in cplug.json is not the name part of the id in carnivore.json")
    if carnivore.get("version") != cplug.get("version"):
        raise PackError("cplug.json and carnivore.json carry different versions")
    names = _permission_names(carnivore.get("permissions"))
    if sorted(names) != sorted((cplug.get("permissions") or {}).get("app", [])):
        raise PackError("cplug.json permissions.app and the carnivore.json permission names differ")
    if (carnivore.get("page") is not None or carnivore.get("topics") is not None) and vtuple(str(carnivore.get("min_app_version") or "0")) < vtuple(PAGE_TOPICS_FLOOR):
        raise PackError(f"page and topics need min_app_version {PAGE_TOPICS_FLOOR} or later")
    return Packed(dict(carnivore), dict(cplug))


def pack_files(files: Mapping[str, bytes], publisher: Optional[str] = None) -> Tuple[Dict[str, bytes], Packed]:
    side_raw = files.get(CARNIVORE_FILE)
    try:
        authored = json.loads(side_raw.decode("utf-8")) if side_raw is not None else None
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackError("carnivore.json is not valid json") from exc
    if not isinstance(authored, dict):
        raise PackError("the folder needs a carnivore.json object")
    if not is_authored(authored):
        runtime = files.get(CPLUG_FILE)
        try:
            decoded = json.loads(runtime.decode("utf-8")) if runtime is not None else None
        except (UnicodeDecodeError, ValueError) as exc:
            raise PackError("cplug.json is not valid json") from exc
        if not isinstance(decoded, dict):
            raise PackError("the folder needs a cplug.json object (or author one carnivore.json with a sidecar key)")
        return dict(files), check_pair(authored, decoded)
    if CPLUG_FILE in files:
        raise PackError("cplug.json is generated from sidecar; remove it from the source folder")
    packed = pack_manifest(authored, publisher)
    out = dict(files)
    out[CARNIVORE_FILE] = dump(packed.carnivore)
    out[CPLUG_FILE] = dump(packed.cplug)
    return out, packed


def dump(doc: Mapping[str, Any]) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def pack_folder(source: Path, dest: Path, publisher: Optional[str] = None, skip_top: frozenset = frozenset()) -> Packed:
    files: Dict[str, bytes] = {}
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if rel.parts[0] in skip_top or any(part in {"__pycache__", ".git"} or part.startswith("._") or part == ".DS_Store" for part in rel.parts):
            continue
        if path.is_symlink():
            raise PackError(f"{rel.as_posix()} is a link; a plugin ships real files")
        if path.is_file():
            files[rel.as_posix()] = path.read_bytes()
    out, packed = pack_files(files, publisher)
    for rel, body in out.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    return packed
