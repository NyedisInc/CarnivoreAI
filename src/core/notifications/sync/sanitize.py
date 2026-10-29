
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

import structlog

from src.core.notifications import doc_model, kind_specs
from src.core.notifications.destinations import extras as extras_mod
from src.core.notifications.destinations import validate

log = structlog.get_logger(__name__)

MAX_TOMB_SKEW_SECONDS = 24 * 3600
MAX_ENTRIES = 4000
_EXTRA_ROUTE_KEY = {"reminder": "reminder_minutes"}


def _clean_record(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return None
    spec = kind_specs.get_kind(raw.get("kind")) if isinstance(raw.get("kind"), str) else None
    if spec is None or spec.virtual or not isinstance(raw.get("enabled"), bool):
        return None
    names = raw.get("secret_fields", [])
    allowed = {f.name for f in spec.secret_fields}
    rev = raw.get("secret_rev", 0)
    if not isinstance(names, list) or not all(isinstance(n, str) and n in allowed for n in names):
        return None
    if isinstance(rev, bool) or not isinstance(rev, int) or not 0 <= rev <= 10**9:
        return None
    config = raw.get("config", {})
    if not isinstance(config, Mapping):
        return None
    try:
        name = validate.check_name(raw.get("name"))
        public = validate.typed_config(
            spec, validate.validate_fields(spec.public_fields, config, spec, apply_defaults=False))
    except validate.InvalidDestination:
        return None
    return {"kind": spec.id, "name": name, "enabled": raw["enabled"], "config": public,
            "secret_fields": sorted(set(names)), "secret_rev": rev}


def _clean_value(path: str, raw: Any) -> Tuple[bool, Any]:
    parsed = doc_model.parse_path(path)
    if parsed.kind == doc_model.KIND_DEST:
        record = _clean_record(raw)
        return record is not None, record
    if parsed.kind in (doc_model.KIND_TICK, doc_model.KIND_DEFAULT, doc_model.KIND_MUTE):
        return isinstance(raw, bool), raw
    if parsed.kind == doc_model.KIND_EXTRA and parsed.extra is not None:
        try:
            return True, extras_mod.check_value(_EXTRA_ROUTE_KEY.get(parsed.extra, parsed.extra), raw)
        except validate.InvalidDestination:
            return False, None
    return False, None


def clean_entry(path: Any, entry: Any, now: float) -> Optional[Dict[str, Any]]:
    if not isinstance(path, str) or not isinstance(entry, Mapping) or doc_model.is_local_only(path):
        return None
    try:
        parsed = doc_model.parse_path(path)
        ver = doc_model.parse_version(entry.get("ver"))
    except ValueError:
        return None
    ids = [x for x in (parsed.dest, parsed.col) if x]
    if any(kind_specs.is_push_destination_id(x) for x in ids) or set(entry) - {"val", "tomb", "ver"}:
        return None
    if "tomb" in entry:
        tomb = entry["tomb"]
        if "val" in entry or isinstance(tomb, bool) or not isinstance(tomb, (int, float)):
            return None
        if tomb < 0 or tomb > now + MAX_TOMB_SKEW_SECONDS:
            return None
        return {"tomb": tomb, "ver": [ver[0], ver[1]]}
    if "val" not in entry:
        return None
    ok, value = _clean_value(path, entry["val"])
    return {"val": value, "ver": [ver[0], ver[1]]} if ok else None


def clean_map(raw: Any, now: float) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, Mapping) or len(raw) > MAX_ENTRIES:
        if isinstance(raw, Mapping):
            log.warning("notification_sync_map_too_large", entries=len(raw))
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    dropped = 0
    for path, entry in raw.items():
        cleaned = clean_entry(path, entry, now)
        if cleaned is None:
            dropped += 1
        else:
            out[path] = cleaned
    if dropped:
        log.info("notification_sync_entries_dropped", count=dropped)
    return doc_model.prune_tombstones(out, now)


def live_dest_ids(global_map: Mapping[str, Mapping[str, Any]]) -> List[str]:
    return sorted(p.split("/", 1)[1] for p, e in global_map.items()
                  if p.startswith(doc_model.KIND_DEST + "/") and not doc_model.is_tombstone(e))
