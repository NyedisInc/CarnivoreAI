"""The hierarchical widget and plugin settings object, read and written (issues #727, #888).

ONE OBJECT, THREE LEVELS: kind, item id, field key.

    {"widget": {"core.activity-log": {"enabled": false,
                                      "values": {"showSystem": false},
                                      "revision": 4}},
     "plugin": {}}

A stored key is addressed ``<kind>.<item id>.<field>`` in prose; on the
wire it is nested, because a widget id itself contains a dot
(``core.activity-log``) and a flat dotted key could not be split back.

ABSENT IS NOT A DEFAULT (``docs/ui-preferences-inventory.md``). Only what a
person chose is stored and answered. An item nobody touched is missing
from the object, an ``enabled`` nobody set is missing (``None`` on the
per-item read), and an untouched field is missing from ``values``. The
defaults stay in each item's schema, which the per-item read hands back
so a client resolves them itself.

A STORED VALUE THE CURRENT SCHEMA REFUSES IS DROPPED, NEVER REPAIRED. The
read runs ``item_settings_schema.migrate`` and names the dropped keys, and
the next write to that item leaves them out.

CONCURRENCY. Every write is one ``BEGIN IMMEDIATE`` transaction: read the
item's row, check the caller's ``expected_revision`` against it (409 on a
mismatch, carrying the current item), merge the patch, and write only when
something actually changed. Revisions are document-monotonic (see
``item_settings_ddl.py``), so two writes to DIFFERENT items never refuse
each other, and the object's revision is ``MAX(revision)``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import structlog

from src.core import item_catalog
from src.core.db import transaction
from src.core.item_catalog import ItemDecl
from src.core.item_settings_ddl import ITEM_SETTINGS_TABLE
from src.core.item_settings_schema import SETTING_UNKNOWN, check_key, migrate
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

COMMITTED = "committed"
UNCHANGED = "unchanged"


class ItemSettingsError(Exception):

    code = "item_settings_error"


class ItemUnknown(ItemSettingsError):

    code = "item_unknown"


class EnabledNotSupported(ItemSettingsError):

    code = "enabled_not_supported"


class EmptyPatch(ItemSettingsError):

    code = "empty_patch"


class SettingRefused(ItemSettingsError):

    def __init__(self, code: str, key: str) -> None:
        super().__init__(f"{key}: {code}")
        self.code = code
        self.key = key


class ItemStale(ItemSettingsError):

    code = "item_settings_stale"

    def __init__(self, current: "ItemState") -> None:
        super().__init__("the item changed since it was read")
        self.current = current


@dataclass(frozen=True)
class ItemState:

    kind: str
    item_id: str
    enabled: Optional[bool]
    values: Dict[str, Any]
    dropped: List[str]
    revision: int
    decl: ItemDecl

    def as_payload(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.item_id,
            "enabled": self.enabled,
            "switchable": self.decl.switchable,
            "values": dict(self.values),
            "dropped": list(self.dropped),
            "schema": self.decl.schema.as_wire() if self.decl.schema is not None else None,
            "revision": self.revision,
        }

    def as_node(self) -> Dict[str, Any]:
        node: Dict[str, Any] = {"revision": self.revision}
        if self.enabled is not None:
            node["enabled"] = self.enabled
        if self.values:
            node["values"] = dict(self.values)
        return node


@dataclass(frozen=True)
class WriteResult:

    status: str
    item: ItemState
    document_revision: int = field(default=0)


def _decl(kind: str, item_id: str) -> ItemDecl:
    decl = item_catalog.find(kind, item_id)
    if decl is None:
        raise ItemUnknown(f"no {kind} with id {item_id!r}")
    return decl


def _state_from(decl: ItemDecl, row: Optional[sqlite3.Row]) -> ItemState:
    if row is None:
        return ItemState(decl.kind, decl.id, None, {}, [], 0, decl)
    try:
        raw = json.loads(row["values_json"])
    except ValueError:
        raw = None
    if not isinstance(raw, dict):
        logger.warning("item_settings_values_unreadable", kind=decl.kind, item_id=decl.id)
        raw = {}
    values, dropped = migrate(decl.kind, decl.id, row["schema_version"], decl.schema, raw)
    enabled = None if row["enabled"] is None else bool(row["enabled"])
    if not decl.switchable:
        enabled = None
    return ItemState(decl.kind, decl.id, enabled, values, dropped, int(row["revision"]), decl)


def _row(conn: sqlite3.Connection, kind: str, item_id: str) -> Optional[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        f"SELECT * FROM {ITEM_SETTINGS_TABLE} WHERE kind = ? AND item_id = ?", (kind, item_id)
    ).fetchone()


def document_revision(conn: sqlite3.Connection) -> int:
    found = conn.execute(f"SELECT COALESCE(MAX(revision), 0) FROM {ITEM_SETTINGS_TABLE}").fetchone()
    return int(found[0])


def read_item(conn: sqlite3.Connection, kind: str, item_id: str) -> ItemState:
    decl = _decl(kind, item_id)
    return _state_from(decl, _row(conn, kind, item_id))


def read_document(conn: sqlite3.Connection) -> Dict[str, Any]:
    conn.row_factory = sqlite3.Row
    rows = {
        (row["kind"], row["item_id"]): row
        for row in conn.execute(f"SELECT * FROM {ITEM_SETTINGS_TABLE}").fetchall()
    }
    items: Dict[str, Dict[str, Any]] = {}
    for kind, decls in item_catalog.all_items().items():
        nodes: Dict[str, Any] = {}
        for decl in decls:
            row = rows.get((kind, decl.id))
            if row is None:
                continue
            state = _state_from(decl, row)
            if state.enabled is None and not state.values:
                continue
            nodes[decl.id] = state.as_node()
        items[kind] = nodes
    return {"revision": document_revision(conn), "items": items}


def write_item(
    conn: sqlite3.Connection,
    kind: str,
    item_id: str,
    values: Optional[Mapping[str, Any]] = None,
    enabled: Optional[bool] = None,
    expected_revision: Optional[int] = None,
) -> WriteResult:
    decl = _decl(kind, item_id)
    if not values and enabled is None:
        raise EmptyPatch("the patch names nothing to change")
    if enabled is not None and not decl.switchable:
        raise EnabledNotSupported(f"{kind} {item_id} has no on/off choice here")
    for key, value in (values or {}).items():
        if value is None:
            if decl.schema is None or key not in decl.schema.fields:
                raise SettingRefused(SETTING_UNKNOWN, key)
            continue
        code = check_key(decl.schema, key, value)
        if code is not None:
            raise SettingRefused(code, key)

    with transaction(conn):
        current = _state_from(decl, _row(conn, kind, item_id))
        if expected_revision is not None and expected_revision != current.revision:
            raise ItemStale(current)
        merged = dict(current.values)
        for key, value in (values or {}).items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        next_enabled = current.enabled if enabled is None else enabled
        if merged == current.values and next_enabled == current.enabled and not current.dropped:
            return WriteResult(UNCHANGED, current, document_revision(conn))
        revision = document_revision(conn) + 1
        conn.execute(
            f"INSERT INTO {ITEM_SETTINGS_TABLE} "
            "(kind, item_id, enabled, schema_version, values_json, revision, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(kind, item_id) DO UPDATE SET "
            "enabled = excluded.enabled, schema_version = excluded.schema_version, "
            "values_json = excluded.values_json, revision = excluded.revision, "
            "updated_at = excluded.updated_at",
            (
                kind,
                item_id,
                None if next_enabled is None else int(next_enabled),
                decl.schema.version if decl.schema is not None else None,
                json.dumps(merged, sort_keys=True),
                revision,
                utc_now(),
            ),
        )
        stored = _state_from(decl, _row(conn, kind, item_id))
    logger.info("item_settings_written", kind=kind, item_id=item_id, revision=revision,
                keys=sorted((values or {}).keys()), enabled=enabled)
    return WriteResult(COMMITTED, stored, revision)


def widget_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Every declared widget with its EFFECTIVE on/off state, for ``GET /widgets``.

    Description: a switchable widget nobody switched reads ON, the same
      fail-open rule the plugins page carries (an unknown choice is never
      "hide it"); a per-target kind reads ``None`` (no switch).
    Inputs: conn. Output: list[dict] - ``{id, instancing, enabled, has_settings}``.
    """
    out = []
    for decl in item_catalog.items_of(item_catalog.KIND_WIDGET):
        state = _state_from(decl, _row(conn, decl.kind, decl.id))
        enabled = (state.enabled is not False) if decl.switchable else None
        out.append({"id": decl.id, "instancing": decl.instancing, "enabled": enabled,
                    "has_settings": decl.schema is not None and bool(decl.schema.fields)})
    return out
