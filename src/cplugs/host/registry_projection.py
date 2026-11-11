
from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Optional

SCHEMA = 1
"""The ``schema`` number written into ``plugins.json``."""

KIND_FEATURE = "feature"
KIND_PLUGIN = "plugin"
SOURCE_CATALOG = "catalog"
SOURCE_FOLDER = "folder"
LOCAL_PREFIX = "local/"

STATE_DEFAULTS: Dict[str, Any] = {"enabled": False, "grants": [], "settings": {}, "revision": 0, "digest": None, "updated_at": None}
LEDGER_KEYS = ("uuid", "catalog_id", "publisher_key_id")
DOC_NAMES = ("state", "installs", "sideload", "third_party")
_CONTAINER = {"state": "cplugs", "installs": "installs", "sideload": "items", "third_party": "enabled"}
MIRROR_STAMP = "registry_generation"


def _fresh_defaults() -> Dict[str, Any]:
    return copy.deepcopy(STATE_DEFAULTS)


def _mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _state_part(entry: Any) -> Dict[str, Any]:
    if entry is None:
        return {**_fresh_defaults(), "unstored": True}
    if not isinstance(entry, dict):
        return {**_fresh_defaults(), "state_raw": copy.deepcopy(entry)}
    part = {k: copy.deepcopy(v) for k, v in entry.items() if k in STATE_DEFAULTS}
    extra = {k: copy.deepcopy(v) for k, v in entry.items() if k not in STATE_DEFAULTS}
    if extra:
        part["state_extra"] = extra
    return part


def _plugin_part(row: Mapping[str, Any], sideload_item: Any) -> Dict[str, Any]:
    catalog_id = row.get("catalog_id")
    folder = str(catalog_id).startswith(LOCAL_PREFIX)
    part: Dict[str, Any] = {"kind": KIND_PLUGIN, "source": SOURCE_FOLDER if folder else SOURCE_CATALOG, "catalog_id": catalog_id,
                            "install_uuid": row.get("uuid")}
    if "publisher_key_id" in row:
        part["publisher_key_id"] = row["publisher_key_id"]
    remembered = sideload_item.get("source") if isinstance(sideload_item, dict) else None
    path = row.get("source") or remembered
    if path:
        part["source_path"] = path
    extra = {k: copy.deepcopy(v) for k, v in row.items() if k not in LEDGER_KEYS}
    if extra:
        part["ledger_extra"] = extra
    return part


def _tombstone(row: Mapping[str, Any], entry: Any, sideload_item: Any) -> Dict[str, Any]:
    gone = _mapping(row.get("removed"))
    kept = _state_part(entry) if isinstance(entry, dict) else _state_part(None)
    out: Dict[str, Any] = {"catalog_id": row.get("catalog_id"), "install_uuid": row.get("uuid"),
                           "publisher_key_id": gone.get("publisher_key_id") or row.get("publisher_key_id") or None, "version": gone.get("version"),
                           "grants": kept["grants"], "settings": kept["settings"], "removed_at": gone.get("at"), "ledger": copy.deepcopy(dict(row))}
    if entry is not None:
        out["state"] = copy.deepcopy(entry)
    if sideload_item is not None:
        out["sideload_record"] = copy.deepcopy(sideload_item)
    return out


def _others(docs: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    for name in DOC_NAMES:
        doc = _mapping(docs.get(name))
        rest = {k: copy.deepcopy(v) for k, v in doc.items() if k != _CONTAINER[name] and k != MIRROR_STAMP}
        if rest:
            found[name] = rest
    return found


def build_document(*, generation: int, docs: Mapping[str, Any], carry: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    state = _mapping(_mapping(docs.get("state")).get("cplugs"))
    rows = _mapping(_mapping(docs.get("installs")).get("installs"))
    memory = _mapping(_mapping(docs.get("sideload")).get("items"))
    items: Dict[str, Any] = {}
    tombstones: Dict[str, Any] = {}
    for name in sorted(set(state) | set(rows) | set(memory)):
        row, entry, remembered = rows.get(name), state.get(name), memory.get(name)
        if isinstance(row, dict) and row.get("removed"):
            tombstones[name] = _tombstone(row, entry, remembered)
            continue
        item: Dict[str, Any] = _plugin_part(row, remembered) if isinstance(row, dict) else {"kind": KIND_FEATURE}
        item.update(_state_part(entry))
        if remembered is not None:
            item["sideload_record"] = copy.deepcopy(remembered)
        items[name] = item
    document: Dict[str, Any] = {"schema": SCHEMA, "generation": generation,
                                "switches": {"third_party": _mapping(docs.get("third_party")).get("enabled") is True},
                                "items": items, "tombstones": tombstones, "other": _others(docs)}
    for key, value in (carry or {}).items():
        document[key] = copy.deepcopy(value)
    return document


def _state_entry(part: Mapping[str, Any]) -> Any:
    if part.get("unstored") is True:
        return _ABSENT
    if "state_raw" in part:
        return copy.deepcopy(part["state_raw"])
    entry = {k: copy.deepcopy(part[k]) for k in STATE_DEFAULTS if k in part}
    entry.update(copy.deepcopy(_mapping(part.get("state_extra"))))
    return entry


_ABSENT = object()


def _ledger_row(item: Mapping[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {"uuid": item.get("install_uuid"), "catalog_id": item.get("catalog_id")}
    if "publisher_key_id" in item:
        row["publisher_key_id"] = item["publisher_key_id"]
    row.update(copy.deepcopy(_mapping(item.get("ledger_extra"))))
    return row


def join(registry: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    cplugs: Dict[str, Any] = {}
    rows: Dict[str, Any] = {}
    memory: Dict[str, Any] = {}
    for name, item in sorted(_mapping(registry.get("items")).items()):
        entry = _state_entry(item)
        if entry is not _ABSENT:
            cplugs[name] = entry
        if "install_uuid" in item:
            rows[name] = _ledger_row(item)
        if "sideload_record" in item:
            memory[name] = copy.deepcopy(item["sideload_record"])
    for name, tomb in sorted(_mapping(registry.get("tombstones")).items()):
        rows[name] = copy.deepcopy(_mapping(tomb.get("ledger")))
        if "state" in tomb:
            cplugs[name] = copy.deepcopy(tomb["state"])
        if "sideload_record" in tomb:
            memory[name] = copy.deepcopy(tomb["sideload_record"])
    other = _mapping(registry.get("other"))
    docs = {
        "state": {**copy.deepcopy(_mapping(other.get("state"))), "cplugs": cplugs},
        "installs": {**copy.deepcopy(_mapping(other.get("installs"))), "installs": rows},
        "sideload": {**copy.deepcopy(_mapping(other.get("sideload"))), "items": memory},
        "third_party": {**copy.deepcopy(_mapping(other.get("third_party"))), "enabled": bool(_mapping(registry.get("switches")).get("third_party"))},
    }
    return docs


def normalize(docs: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for name in DOC_NAMES:
        doc = {k: copy.deepcopy(v) for k, v in _mapping(docs.get(name)).items() if k != MIRROR_STAMP}
        container = _CONTAINER[name]
        if name == "third_party":
            doc[container] = doc.get(container) is True
        else:
            doc[container] = copy.deepcopy(_mapping(doc.get(container)))
        out[name] = doc
    return out
