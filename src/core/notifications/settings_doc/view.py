
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.core.notifications import doc_model, kind_specs, types
from src.core.notifications.settings_doc import mutes
from src.core.notifications.routing_view import DestinationStatus, DestinationView, QuietHours

SRC_GLOBAL = "global"
SRC_LOCAL = "local"
SRC_LOCKED = "locked"
SRC_DEFAULT = "default"

EXTRA_DEFAULTS: Dict[str, Any] = {"away": False, "quiet": None, "reminder": None, "projects": [], "details": False}


@dataclass(frozen=True)
class Cell:

    value: bool
    source: str
    locked: bool

    def as_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "source": self.source, "locked": self.locked}


def paused(doc: Mapping[str, Any]) -> bool:
    return bool(doc_model.effective_value(doc, doc_model.local_key("paused"), False))


def allow_private_key(dest_id: str) -> str:
    return doc_model.local_key(f"allow_private.{dest_id}")


def switch_on(doc: Mapping[str, Any], key: str) -> bool:
    value = doc["local"].get(key)
    return value is True or (isinstance(value, str) and bool(value))


def switch_origin(doc: Mapping[str, Any], key: str) -> Optional[str]:
    value = doc["local"].get(key)
    return value if isinstance(value, str) and value else None


def allow_private(doc: Mapping[str, Any], dest_id: str) -> bool:
    return switch_on(doc, allow_private_key(dest_id))


def allow_plain_http_key(dest_id: str) -> str:
    return doc_model.local_key(f"allow_plain_http.{dest_id}")


def allow_plain_http(doc: Mapping[str, Any], dest_id: str) -> bool:
    return switch_on(doc, allow_plain_http_key(dest_id))


def default_tick(doc: Mapping[str, Any], type_id: str) -> bool:
    return bool(doc_model.effective_value(doc, doc_model.default_path(type_id), type_id in types.seed_type_ids()))


def cell(doc: Mapping[str, Any], column: str, type_id: str) -> Cell:
    row = types.get_type(type_id)
    if row is None:
        raise ValueError(f"not a notification type: {type_id!r}")
    if column == doc_model.COL_SCREEN:
        fallback = row.defaults.screen
    else:
        if row.defaults.outside_locked_off:
            return Cell(False, SRC_LOCKED, True)
        fallback = False
    path = doc_model.tick_path(column, type_id)
    source = doc_model.effective_source(doc, path)
    if source == "absent":
        return Cell(fallback, SRC_DEFAULT, False)
    return Cell(bool(doc_model.effective_value(doc, path, fallback)), source, False)


def dest_ids(doc: Mapping[str, Any]) -> List[str]:
    ids = set()
    for path, entry in doc["global"].items():
        if path.startswith(doc_model.KIND_DEST + "/") and not doc_model.is_tombstone(entry):
            ids.add(path.split("/", 1)[1])
    for path in doc["local"]:
        if path.startswith(doc_model.KIND_DEST + "/") and kind_specs.is_destination_id(path.split("/", 1)[1]):
            ids.add(path.split("/", 1)[1])
    return sorted(ids)


def dest_scope(doc: Mapping[str, Any], dest_id: str) -> Optional[str]:
    path = doc_model.dest_path(dest_id)
    entry = doc["global"].get(path)
    if entry is not None and not doc_model.is_tombstone(entry):
        return SRC_GLOBAL
    return SRC_LOCAL if isinstance(doc["local"].get(path), dict) else None


def dest_record(doc: Mapping[str, Any], dest_id: str) -> Optional[Dict[str, Any]]:
    scope = dest_scope(doc, dest_id)
    if scope is None:
        return None
    path = doc_model.dest_path(dest_id)
    base = dict(doc["global"][path]["val"]) if scope == SRC_GLOBAL else {}
    overlay = doc["local"].get(path)
    return {**base, **(overlay if isinstance(overlay, dict) else {})}


def is_pinned_dest(doc: Mapping[str, Any], dest_id: str) -> bool:
    return dest_scope(doc, dest_id) == SRC_GLOBAL and doc_model.is_pinned(doc, doc_model.dest_path(dest_id))


def extras(doc: Mapping[str, Any], dest_id: str) -> Dict[str, Any]:
    raw = {name: doc_model.effective_value(doc, doc_model.extra_path(dest_id, name), EXTRA_DEFAULTS[name])
           for name in doc_model.EXTRAS}
    return {"away": bool(raw["away"]), "quiet": raw["quiet"], "reminder_minutes": raw["reminder"],
            "projects": list(raw["projects"] or []), "details": bool(raw["details"])}


def destination_dict(doc: Mapping[str, Any], dest_id: str) -> Optional[Dict[str, Any]]:
    record = dest_record(doc, dest_id)
    spec = kind_specs.get_kind(record["kind"]) if record else None
    if record is None or spec is None:
        return None
    set_names = set(record.get("secret_fields") or [])
    return {
        "id": dest_id, "kind": spec.id, "name": record.get("name", ""), "enabled": bool(record.get("enabled", True)),
        "scope": dest_scope(doc, dest_id), "pinned": is_pinned_dest(doc, dest_id),
        "config": dict(record.get("config") or {}),
        "allow_private": bool(spec.allow_private and allow_private(doc, dest_id)),
        "allow_plain_http": bool(spec.allow_private and allow_plain_http(doc, dest_id)),
        "secrets": {f.name: {"set": f.name in set_names} for f in spec.secret_fields},
        "extras": extras(doc, dest_id), "status": None,
        "disabled_reason": None if record.get("enabled", True) else record.get("disabled_reason"),
    }


def status_json(item: Mapping[str, Any], status: Optional[DestinationStatus]) -> Optional[Dict[str, Any]]:
    reason = item.get("disabled_reason")
    if status is None and not reason:
        return None
    out = asdict(status if status is not None else DestinationStatus())
    if reason and not out.get("disabled_reason"):
        out["disabled_reason"] = reason
    return out


def _quiet(raw: Any) -> Optional[QuietHours]:
    if isinstance(raw, Mapping) and isinstance(raw.get("start"), str) and isinstance(raw.get("end"), str):
        return QuietHours(raw["start"], raw["end"])
    return None


def _switch_config(doc: Mapping[str, Any], d: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, key in (("allow_private", allow_private_key(d["id"])), ("allow_plain_http", allow_plain_http_key(d["id"]))):
        if d[name]:
            out[name] = True
            out[f"{name}_origin"] = switch_origin(doc, key) or ""
    return out


def destination_view(doc: Mapping[str, Any], dest_id: str) -> Optional[DestinationView]:
    d = destination_dict(doc, dest_id)
    if d is None:
        return None
    x = d["extras"]
    return DestinationView(
        id=d["id"], kind=d["kind"], name=d["name"], enabled=d["enabled"], scope=d["scope"],
        config={**d["config"], **_switch_config(doc, d)},
        details=x["details"], away=x["away"], quiet=_quiet(x["quiet"]), reminder_minutes=x["reminder_minutes"],
        projects=tuple(x["projects"]),
    )


def webpush_view(doc: Mapping[str, Any], sub_id: str, name: str) -> DestinationView:
    return _push_view(doc, kind_specs.webpush_destination_id(sub_id), kind_specs.KIND_WEBPUSH, name)


def apns_view(doc: Mapping[str, Any], device_row_id: str, name: str) -> DestinationView:
    return _push_view(doc, kind_specs.apns_destination_id(device_row_id), kind_specs.KIND_APNS, name)


def _push_view(doc: Mapping[str, Any], dest_id: str, kind: str, name: str) -> DestinationView:
    x = extras(doc, dest_id)
    return DestinationView(
        id=dest_id, kind=kind, name=name, enabled=True, scope=SRC_LOCAL, config={}, details=False,
        away=x["away"], quiet=_quiet(x["quiet"]), reminder_minutes=x["reminder_minutes"], projects=tuple(x["projects"]),
    )


class DocRoutingView:

    def __init__(self, doc: Mapping[str, Any], webpush: Sequence[DestinationView] = (),
                 push_owners: Optional[Mapping[str, str]] = None) -> None:
        self._doc = doc
        self._push_owners: Mapping[str, str] = dict(push_owners or {})
        self.revision: int = int(doc.get("rev", 0))
        self.paused: bool = paused(doc)
        views = (destination_view(doc, i) for i in dest_ids(doc))
        self._destinations: Sequence[DestinationView] = tuple(v for v in views if v is not None) + tuple(webpush)

    def destinations(self) -> Sequence[DestinationView]:
        return self._destinations

    def is_ticked(self, column: str, type_id: str) -> bool:
        try:
            if mutes.is_muted_for(self._doc, type_id, self._push_owners.get(column)):
                return False
            return cell(self._doc, column, type_id).value
        except (KeyError, ValueError):
            return False
