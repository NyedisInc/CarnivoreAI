
from __future__ import annotations

from typing import Any, Dict, Optional

from src.core.notifications import doc_model, kind_specs, types
from src.core.notifications.settings_doc import view
from src.core.notifications.settings_doc.store import PAUSED_KEY, Doc, SettingsDocStore

SCOPE_GLOBAL = "global"
SCOPE_LOCAL = "local"


class LockedCell(ValueError):
    pass


class UnknownDestination(LookupError):
    pass


def _check_column(doc: Doc, column: str) -> bool:
    if column == doc_model.COL_SCREEN or kind_specs.is_push_destination_id(column):
        return kind_specs.is_push_destination_id(column)
    if not kind_specs.is_destination_id(column):
        raise ValueError(f"not a column: {column!r}")
    scope = view.dest_scope(doc, column)
    if scope is None:
        raise UnknownDestination(column)
    return scope == view.SRC_LOCAL


def write_value(doc: Doc, me: str, path: str, value: Any, scope: Optional[str], always_local: bool = False) -> Doc:
    local = always_local or scope == SCOPE_LOCAL or (scope is None and doc_model.is_pinned(doc, path))
    if local:
        return doc_model.set_local(doc, path, value)
    return doc_model.set_global(doc, path, value, me)


def put_tick(store: SettingsDocStore, column: str, type_id: str, value: bool, scope: Optional[str] = None) -> view.Cell:
    if scope not in (None, SCOPE_GLOBAL, SCOPE_LOCAL):
        raise ValueError("scope must be global or local")
    if not types.is_registered(type_id):
        raise ValueError(f"not a notification type: {type_id!r}")

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        always_local = _check_column(doc, column)
        if view.cell(doc, column, type_id).locked:
            raise LockedCell(f"{column}/{type_id} is locked")
        return write_value(doc, me, doc_model.tick_path(column, type_id), bool(value), scope, always_local)

    return view.cell(store.update(mutate), column, type_id)


def put_default(store: SettingsDocStore, type_id: str, value: bool) -> Dict[str, bool]:
    if not types.is_registered(type_id):
        raise ValueError(f"not a notification type: {type_id!r}")
    doc = store.update(lambda d, me: doc_model.set_global(d, doc_model.default_path(type_id), bool(value), me))
    return {row.id: view.default_tick(doc, row.id) for row in types.ordered_types()}


def reset_override(store: SettingsDocStore, path: str) -> bool:
    parsed = doc_model.parse_path(path)
    if parsed.kind == doc_model.KIND_LOCAL:
        raise ValueError("a local-only key cannot be reset")
    state = {"was": False}

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        if not doc_model.is_pinned(doc, path):
            return None
        owner = parsed.dest if parsed.kind in (doc_model.KIND_DEST, doc_model.KIND_EXTRA) else parsed.col
        if owner and kind_specs.is_destination_id(owner) and view.dest_scope(doc, owner) == view.SRC_LOCAL:
            raise ValueError("not resettable")
        state["was"] = True
        return doc_model.clear_local(doc, path)

    store.update(mutate)
    return state["was"]


def set_paused(store: SettingsDocStore, value: bool) -> bool:
    store.update(lambda d, me: None if bool(doc_model.effective_value(d, PAUSED_KEY, False)) == bool(value)
                 else doc_model.set_local(d, PAUSED_KEY, bool(value)))
    return bool(value)
