
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Any, Dict, List, Mapping, Optional

from src.cplugs.huddle import rules

INSTALL, REBOOT, PERSON, CHILDREN, OTHER = "install", "reboot", "person", "children", "other"
KINDS = (INSTALL, REBOOT, PERSON, CHILDREN, OTHER)
HOLD_TEXT = "its forked tasks"
HOLDING_STATES = (rules.OPEN, rules.WAITING)
_HOLDING_LIST = ", ".join(f"'{s}'" for s in HOLDING_STATES)
HOLDING_COUNT_SQL = "(SELECT COUNT(*) FROM work_items c WHERE c.forked_from = {parent} AND c.deleted = 0 AND c.state IN (" + _HOLDING_LIST + "))"

SELECT_COL = ("COALESCE((SELECT json_group_array(json_object('id', b.id, 'kind', b.kind, 'text', b.text, 'evidence', b.evidence, "
              "'created_by', b.created_by, 'created_at', b.created_at, 'holding', CASE WHEN b.kind = 'children' THEN "
              + HOLDING_COUNT_SQL.format(parent="b.item_id") + " END)) FROM work_blockers b "
              "WHERE b.item_id = work_items.id AND b.cleared_at IS NULL), '[]') AS blockers_json")
FIELD = "blockers"


def wire(row: Mapping[str, Any]) -> Dict[str, Any]:
    if "blockers_json" not in row.keys():
        return {}
    found = json.loads(row["blockers_json"] or "[]")
    return {FIELD: found} if found else {}


def entry_dict(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {"id": row["id"], "item": row["item_id"], "kind": row["kind"], "text": row["text"], "evidence": row["evidence"],
            "created_by": row["created_by"], "created_at": row["created_at"], "cleared_by": row["cleared_by"], "cleared_at": row["cleared_at"]}


def holding(conn: sqlite3.Connection, item_id: int) -> int:
    return conn.execute("SELECT " + HOLDING_COUNT_SQL.format(parent="?"), (item_id,)).fetchone()[0]


def open_count(conn: sqlite3.Connection, item_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM work_blockers WHERE item_id = ? AND cleared_at IS NULL", (item_id,)).fetchone()[0]


def set_hold(conn: sqlite3.Connection, item_id: int, *, by: str, now: float) -> int:
    found = conn.execute("SELECT id FROM work_blockers WHERE item_id = ? AND kind = ? AND cleared_at IS NULL ORDER BY id LIMIT 1", (item_id, CHILDREN)).fetchone()
    if found is not None:
        return int(found["id"])
    cur = conn.execute("INSERT INTO work_blockers (item_id, kind, text, evidence, created_by, created_at) VALUES (?, ?, ?, '', ?, ?)",
                       (item_id, CHILDREN, HOLD_TEXT, by or rules.CARNIVORE_KEY, now))
    return int(cur.lastrowid)


def clear_all(conn: sqlite3.Connection, item_id: int, *, by: str, now: float) -> int:
    return conn.execute("UPDATE work_blockers SET cleared_by = ?, cleared_at = ? WHERE item_id = ? AND cleared_at IS NULL", (by, now, item_id)).rowcount


def is_held(conn: sqlite3.Connection, item_id: int, now: float) -> bool:
    held = False
    for row in conn.execute("SELECT id, kind FROM work_blockers WHERE item_id = ? AND cleared_at IS NULL", (item_id,)).fetchall():
        if row["kind"] == CHILDREN and not holding(conn, item_id):
            conn.execute("UPDATE work_blockers SET cleared_by = ?, cleared_at = ? WHERE id = ? AND cleared_at IS NULL", (rules.CARNIVORE_KEY, now, row["id"]))
        else:
            held = True
    return held


def on_move(conn: sqlite3.Connection, row: Mapping[str, Any], new_state: str, actor: str, decided: Optional[Any], now: float) -> None:
    if new_state == row["state"]:
        return
    if new_state in rules.APPROVED_STATES or (actor == rules.JOE and row["state"] == rules.WAITING):
        clear_all(conn, row["id"], by=decided.by if decided is not None else rules.OWNER_KEY, now=now)


class BlockerStore:

    def __init__(self, store: Any) -> None:
        self._store = store

    def for_item(self, item_id: int, *, include_cleared: bool = False) -> List[Dict[str, Any]]:
        where = "" if include_cleared else " AND cleared_at IS NULL"
        with closing(self._store._read_connection()) as conn:
            return [entry_dict(r) for r in conn.execute(f"SELECT * FROM work_blockers WHERE item_id = ?{where} ORDER BY id", (item_id,))]

    def releasable(self) -> List[Dict[str, Any]]:
        with closing(self._store._read_connection()) as conn:
            rows = conn.execute("SELECT b.id, b.item_id, b.created_by FROM work_blockers b JOIN work_items i ON i.id = b.item_id WHERE b.kind = ? AND b.cleared_at IS NULL "
                                "AND i.deleted = 0 AND " + HOLDING_COUNT_SQL.format(parent="b.item_id") + " = 0 ORDER BY b.id", (CHILDREN,)).fetchall()
        return [dict(r) for r in rows]

    def claim_release(self, blocker_id: int) -> Optional[Dict[str, Any]]:
        with closing(self._store._connect(True)) as conn, conn:
            cur = conn.execute("UPDATE work_blockers SET cleared_by = ?, cleared_at = ? WHERE id = ? AND cleared_at IS NULL AND "
                               + HOLDING_COUNT_SQL.format(parent="work_blockers.item_id") + " = 0", (rules.CARNIVORE_KEY, self._store._clock(), blocker_id))
            if cur.rowcount != 1:
                return None
            item_id = conn.execute("SELECT item_id FROM work_blockers WHERE id = ?", (blocker_id,)).fetchone()["item_id"]
            after = self._touch(conn, item_id)
        self._store._commit_notify(after["list_key"])
        return after

    def clear_hold(self, item_id: int, by: str) -> Optional[Dict[str, Any]]:
        with self._store._immediate() as conn:
            found = conn.execute("SELECT 1 FROM work_items WHERE id = ? AND deleted = 0", (item_id,)).fetchone()
            if found is None or not clear_all(conn, item_id, by=by or rules.CARNIVORE_KEY, now=self._store._clock()):
                return None
            after = self._touch(conn, item_id)
        self._store._commit_notify(after["list_key"])
        return after

    def _touch(self, conn: sqlite3.Connection, item_id: int) -> Dict[str, Any]:
        seq = self._store._next_seq(conn)
        conn.execute("UPDATE work_items SET revision = revision + 1, seq = ?, updated_at = ? WHERE id = ?", (seq, self._store._clock(), item_id))
        row = conn.execute("SELECT state, revision, list_key FROM work_items WHERE id = ?", (item_id,)).fetchone()
        return {"item_id": item_id, "state": row["state"], "revision": row["revision"], "list_key": row["list_key"]}
