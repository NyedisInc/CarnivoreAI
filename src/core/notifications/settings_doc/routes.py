
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.core.notifications import doc_model, kind_specs, types
from src.core.notifications.settings_doc import styles_store
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore

SRC_GLOBAL, SRC_DEFAULT, SRC_UNKNOWN, SRC_LOCKED = "global", "default", "unknown", "locked"
MIGRATED_KEY = doc_model.local_key("routes_migrated")
_OUTSIDE = ("phone", "corner")
_TARGET_COLUMN = {"app": doc_model.COL_SCREEN, "desk": doc_model.COL_DESKTOP}


class UnknownComputer(LookupError):
    pass


@dataclass(frozen=True)
class Resolved:

    value: Optional[bool]
    source: str
    locked: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "source": self.source, "locked": self.locked}


def is_locked(type_id: str, target: str) -> bool:
    row = types.get_type(type_id)
    return bool(row is not None and row.defaults.outside_locked_off and target in _OUTSIDE)


def master_on(doc: Mapping[str, Any], type_id: str) -> bool:
    return doc_model.effective_value(doc, doc_model.on_path(type_id), True) is not False


def _push_ticks(doc: Mapping[str, Any], type_id: str) -> List[bool]:
    out: List[bool] = []
    for path, value in doc["local"].items():
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == doc_model.KIND_TICK and parts[2] == type_id \
                and kind_specs.is_push_destination_id(parts[1]) and isinstance(value, bool):
            out.append(value)
    return out


def _legacy(doc: Mapping[str, Any], target: str, type_id: str) -> Resolved:
    from src.core.notifications.settings_doc import view  # noqa: PLC0415

    if target in _TARGET_COLUMN:
        legacy = view.legacy_cell(doc, _TARGET_COLUMN[target], type_id)
        return Resolved(legacy.value, SRC_DEFAULT if legacy.source == view.SRC_DEFAULT else SRC_GLOBAL)
    if target == "phone":
        ticks = _push_ticks(doc, type_id)
        return Resolved(any(ticks), SRC_DEFAULT)
    stored = doc_model.effective_source(doc, doc_model.corner_key(type_id)) != "absent"
    return Resolved(styles_store.corner_legacy(doc, type_id), SRC_GLOBAL if stored else SRC_DEFAULT)


def resolve(doc: Mapping[str, Any], self_iid: Optional[str], iid: str, target: str, type_id: str) -> Resolved:
    if is_locked(type_id, target):
        return Resolved(False, SRC_LOCKED, True)
    path = doc_model.route_path(iid, target, type_id)
    if doc_model.effective_source(doc, path) != "absent":
        return Resolved(bool(doc_model.effective_value(doc, path, False)), SRC_GLOBAL)
    if iid == self_iid:
        return _legacy(doc, target, type_id)
    if target == "app":
        return _legacy(doc, "app", type_id)
    return Resolved(None, SRC_UNKNOWN)


def cells_for_type(doc: Mapping[str, Any], self_iid: Optional[str], iids: Iterable[str], type_id: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {i: {t: resolve(doc, self_iid, i, t, type_id).as_dict() for t in doc_model.ROUTE_TARGETS} for i in iids}


def put_routes(store: SettingsDocStore, type_ids: Sequence[str], iid: str, target: str, value: bool,
               self_iid: Optional[str], known_iids: Iterable[str]) -> Tuple[List[str], Doc]:
    if iid != self_iid and iid not in set(known_iids):
        raise UnknownComputer(iid)
    if target not in doc_model.ROUTE_TARGETS:
        raise doc_model.SettingsValueError("bad target")
    canon = [types.canonical(t) for t in type_ids]
    if not canon or any(not types.is_registered(t) for t in canon):
        raise doc_model.SettingsValueError("bad type")
    skipped = [t for t in canon if is_locked(t, target)]
    todo = [t for t in dict.fromkeys(canon) if t not in skipped]

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        out, changed = doc, False
        for t in todo:
            path = doc_model.route_path(iid, target, t)
            if doc_model.effective_source(out, path) != "absent" and doc_model.effective_value(out, path) is bool(value):
                continue
            out, changed = doc_model.set_global(out, path, bool(value), me), True
        return out if changed else None

    return skipped, store.update(mutate)


def put_master(store: SettingsDocStore, type_ids: Sequence[str], value: bool) -> Doc:
    canon = [types.canonical(t) for t in type_ids]
    if not canon or any(not types.is_registered(t) for t in canon):
        raise doc_model.SettingsValueError("bad type")

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        out, changed = doc, False
        for t in dict.fromkeys(canon):
            path = doc_model.on_path(t)
            if doc_model.effective_source(out, path) != "absent" and doc_model.effective_value(out, path) is bool(value):
                continue
            out, changed = doc_model.set_global(out, path, bool(value), me), True
        return out if changed else None

    return store.update(mutate)


def migrate_legacy(store: SettingsDocStore, self_iid: str) -> int:
    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        out = doc
        if doc["local"].get(doc_model.SELF_IID_KEY) != self_iid:
            out = doc_model.set_local(out, doc_model.SELF_IID_KEY, self_iid)
        if doc["local"].get(MIGRATED_KEY) is not True:
            for row in types.ordered_types():
                for target, value in _stored_legacy(doc, row.id):
                    if is_locked(row.id, target):
                        continue
                    path = doc_model.route_path(self_iid, target, row.id)
                    if doc_model.effective_source(out, path) == "absent":
                        out = doc_model.set_global(out, path, value, me)
            out = doc_model.set_local(out, MIGRATED_KEY, True)
        return None if out is doc else out

    before = store.snapshot()
    after = store.update(mutate)
    return sum(1 for p in after["global"] if p.startswith(doc_model.KIND_ROUTE + "/") and p not in before["global"])


def _stored_legacy(doc: Mapping[str, Any], type_id: str) -> List[Tuple[str, bool]]:
    out: List[Tuple[str, bool]] = []
    for target, column in _TARGET_COLUMN.items():
        path = doc_model.tick_path(column, type_id)
        if doc_model.effective_source(doc, path) != "absent":
            out.append((target, bool(doc_model.effective_value(doc, path))))
    ticks = _push_ticks(doc, type_id)
    if ticks and len(set(ticks)) == 1:
        out.append(("phone", ticks[0]))
    if doc_model.effective_source(doc, doc_model.corner_key(type_id)) != "absent":
        out.append(("corner", styles_store.corner_legacy(doc, type_id)))
    return out
