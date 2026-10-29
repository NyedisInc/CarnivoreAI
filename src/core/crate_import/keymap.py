
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import structlog

from src.core.crate_import import ledger
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.keyrules import LIST_KEY, NULL_FOREIGN, REF, SELF, rule_for
from src.core.inventory.model import MAIN_STORE
from src.core.inventory.registry_side import SIDE_DBS, side_db_path

logger = structlog.get_logger()

INSERT = "insert"
PRESENT = "present"
KEPT_LOCAL = "kept_local"

NATURAL_KEYS: Dict[str, Tuple[str, ...]] = {
    f"{MAIN_STORE}.companies": ("uid",),
    f"{MAIN_STORE}.projects": ("uid",),
    f"{MAIN_STORE}.sessions": ("session_uuid",),
    f"{MAIN_STORE}.session_notes": ("session_uuid",),
    f"{MAIN_STORE}.session_groups": ("group_uuid",),
    f"{MAIN_STORE}.layouts": ("layout_uuid",),
    f"{MAIN_STORE}.lineage_nodes": ("node_id",),
    f"{MAIN_STORE}.session_conversations": ("session_uuid", "conversation_id"),
    f"{MAIN_STORE}.conversation_index": ("conversation_id",),
    f"{MAIN_STORE}.conversation_milestones": ("conversation_id", "session_uuid"),
    "stats.db.stats_annotations": ("id",),
    "bookmarks.db.bookmarks": ("entry_uuid",),
    "automations.db.automations": ("automation_id",),
    "automations.db.runs": ("run_id",),
}
PRESENCE_ONLY = frozenset({f"{MAIN_STORE}.sessions", "stats.db.stats_annotations"})

_VOLATILE = frozenset({"updated_at", "last_opened_at", "presence", "presence_checked_at", "presence_detail", "lifecycle_checked_at"})


class LocalTables:

    def __init__(self, env: ImportEnv, main: sqlite3.Connection) -> None:
        self._env, self._main = env, main
        self._side: Dict[str, Optional[sqlite3.Connection]] = {}

    def __enter__(self) -> "LocalTables":
        return self

    def __exit__(self, *exc: Any) -> None:
        for conn in self._side.values():
            if conn is not None:
                conn.close()

    def _conn(self, store: str) -> Optional[sqlite3.Connection]:
        if store == MAIN_STORE:
            return self._main
        if store not in self._side:
            path = side_db_path(Path(self._env.state), store) if store in SIDE_DBS else None
            conn: Optional[sqlite3.Connection] = None
            if path is not None and path.is_file():
                try:
                    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                    conn.row_factory = sqlite3.Row
                except sqlite3.Error as exc:
                    logger.warning("crate_import_side_db_unreadable", store=store, error=str(exc))
            self._side[store] = conn
        return self._side[store]

    def find(self, store: str, table: str, key: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        conn = self._conn(store)
        if conn is None or any(v is None for v in key.values()):
            return None
        where = " AND ".join(f"{c} = ?" for c in key)
        try:
            row = conn.execute(f"SELECT * FROM {table} WHERE {where} LIMIT 1", tuple(key.values())).fetchone()
        except sqlite3.Error:
            return None
        return dict(row) if row is not None else None

    def has_identical(self, store: str, table: str, row: Mapping[str, Any], maps: Optional["KeyMaps"] = None) -> bool:
        conn = self._conn(store)
        values = identity_values(store, table, row, maps)
        if conn is None or not values:
            return False
        try:
            live = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            values = {c: v for c, v in values.items() if c in live}
            if not values:
                return False
            where = " AND ".join(f'"{c}" IS ?' for c in values)
            return conn.execute(f'SELECT 1 FROM "{table}" WHERE {where} LIMIT 1', tuple(values.values())).fetchone() is not None
        except sqlite3.Error:
            return False


class KeyMaps:

    def __init__(self, conn: sqlite3.Connection, source_install: Optional[str]) -> None:
        self._conn, self._install = conn, source_install
        self._cache: Dict[str, Dict[str, Any]] = {}

    def table(self, name: str, store: str = MAIN_STORE) -> Dict[str, Any]:
        key = f"{store}.{name}"
        if key not in self._cache:
            self._cache[key] = dict(prior_for(self._conn, self._install, store, name))
        return self._cache[key]


def identity_values(store: str, table: str, row: Mapping[str, Any], maps: Optional[KeyMaps] = None) -> Optional[Dict[str, Any]]:
    out: Dict[str, Any] = {}
    for column, value in row.items():
        rule = rule_for(store, table, column)
        if column == "id" and (rule is None or rule.kind == SELF):
            continue
        if rule is not None and rule.kind == REF and value is not None and (rule.target or "").endswith(".id"):
            mapped = maps.table(str(rule.target).split(".")[0]).get(str(value)) if maps is not None else None
            if mapped is None:
                return None
            value = mapped
        elif rule is not None and rule.kind == LIST_KEY and maps is not None and str(value).isdigit():
            mapped = maps.table("projects").get(str(value))
            value = str(mapped) if mapped is not None else value
        out[column] = value
    return out


def comparable(store: str, table: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for column, value in row.items():
        rule = rule_for(store, table, column)
        if column in _VOLATILE or (rule is not None and rule.kind in (SELF, REF, NULL_FOREIGN, LIST_KEY)):
            continue
        out[column] = value
    return out


def classify_row(local: LocalTables, store: str, table: str, row: Mapping[str, Any], prior_keys: Mapping[str, Any],
                 maps: Optional[KeyMaps] = None) -> str:
    natural = NATURAL_KEYS.get(f"{store}.{table}")
    if natural is None:
        old_id = row.get("id")
        new_id = prior_keys.get(str(old_id)) if old_id is not None else None
        if new_id is None:
            return PRESENT if local.has_identical(store, table, row, maps) else INSERT
        here = local.find(store, table, {"id": new_id})
        return PRESENT if here is not None and not here.get("deleted") else INSERT
    here = local.find(store, table, {c: row.get(c) for c in natural})
    if here is None:
        return INSERT
    if f"{store}.{table}" in PRESENCE_ONLY:
        return PRESENT
    ours, theirs = comparable(store, table, here), comparable(store, table, row)
    shared = set(ours) & set(theirs)
    return PRESENT if all(ours[c] == theirs[c] for c in shared) else KEPT_LOCAL


def prior_for(conn: sqlite3.Connection, source_install: Optional[str], store: str, table: str) -> Dict[str, Any]:
    return ledger.known_keys(conn, source_install, f"{store}.{table}") if source_install else {}

