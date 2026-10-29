
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from src.core.pack.migrate import task_manager_names

IMPORT_BY = "carnivore"
IMPORT_DETAIL = "imported"
STATE_KIND = "state"
OPEN_INBOX = ("queued", "filing")
FILED = "filed"
_INBOX_COLS = ("raw_text", "author", "created_at", "status", "delivered_at", "delivered_to", "filed_at", "error")
_BLOCKER_COLS = ("kind", "text", "evidence", "created_by", "created_at", "cleared_by", "cleared_at")


def _tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _rows(conn: sqlite3.Connection, sql: str, args: Sequence[Any]) -> List[Dict[str, Any]]:
    cur = conn.execute(sql, tuple(args))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def export_of(conn: sqlite3.Connection, items: Sequence[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    ids = [i["id"] for i in items]
    out: Dict[str, List[Dict[str, Any]]] = {"lineage": [], "blockers": [], "inbox": []}
    if not ids:
        return out
    marks = ",".join("?" * len(ids))
    tables = _tables(conn)
    out["lineage"] = _lineage_rows(conn, tables, ids)
    if "work_blockers" in tables:
        out["blockers"] = _rows(conn, f"SELECT * FROM work_blockers WHERE item_id IN ({marks}) ORDER BY id", ids)
    entries = sorted({i["inbox_id"] for i in items if i.get("inbox_id") is not None})
    if "work_inbox" in tables and entries:
        out["inbox"] = _rows(conn, f"SELECT * FROM work_inbox WHERE id IN ({','.join('?' * len(entries))}) ORDER BY id", entries)
    return out


def _lineage_rows(conn: sqlite3.Connection, tables: set, ids: Sequence[int]) -> List[Dict[str, Any]]:
    marks = ",".join("?" * len(ids))
    rows: List[Dict[str, Any]] = []
    if "work_card_events" in tables:
        rows = _rows(conn, f"SELECT item_id, list_key, at, from_col AS from_state, to_col AS to_state, by, detail FROM work_card_events "
                           f"WHERE kind = '{STATE_KIND}' AND item_id IN ({marks}) ORDER BY id", ids)
    if "work_item_lineage" in tables:
        have = {r["item_id"] for r in rows}
        rows += [r for r in _rows(conn, f"SELECT item_id, list_key, at, from_state, to_state, by, detail FROM work_item_lineage WHERE item_id IN ({marks}) ORDER BY id", ids)
                 if r["item_id"] not in have]
    return rows


def import_into(conn: sqlite3.Connection, list_key: str, data: Mapping[str, Any], item_map: Mapping[int, int],
                states: Mapping[int, str]) -> Dict[str, List[int]]:
    tables, now = _tables(conn), time.time()
    inbox_ids = _import_inbox(conn, list_key, data, item_map) if "work_inbox" in tables else []
    if "work_card_events" in tables:
        for row in data.get("lineage", []):
            if row.get("item_id") in item_map:
                _lineage(conn, item_map[row["item_id"]], list_key, row.get("at", now), task_manager_names.current_state(row.get("from_state", "")),
                         task_manager_names.current_state(row.get("to_state", "")), str(row.get("by") or ""), str(row.get("detail") or ""))
        for target_id in item_map.values():
            _lineage(conn, target_id, list_key, now, states[target_id], states[target_id], IMPORT_BY, IMPORT_DETAIL)
    if "work_blockers" in tables:
        for row in data.get("blockers", []):
            if row.get("item_id") in item_map:
                conn.execute(f"INSERT INTO work_blockers (item_id, {', '.join(_BLOCKER_COLS)}) VALUES (?, {', '.join('?' * len(_BLOCKER_COLS))})",
                             (item_map[row["item_id"]], *[row.get(c) for c in _BLOCKER_COLS]))
    return {"inbox_ids": inbox_ids}


def _lineage(conn: sqlite3.Connection, item_id: int, list_key: str, at: float, from_state: str, to_state: str, by: str, detail: str) -> None:
    conn.execute("INSERT INTO work_card_events (item_id, list_key, at, kind, from_col, to_col, by, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (item_id, list_key, at, STATE_KIND, from_state, to_state, by, detail))


def _ids(raw: Any) -> List[int]:
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [i for i in parsed if isinstance(i, int) and not isinstance(i, bool)] if isinstance(parsed, list) else []


def _import_inbox(conn: sqlite3.Connection, list_key: str, data: Mapping[str, Any], item_map: Mapping[int, int]) -> List[int]:
    entry_map: Dict[int, int] = {}
    for entry in data.get("inbox", []):
        linked = [item_map[i] for i in _ids(entry.get("item_ids")) if i in item_map]
        values = {c: entry.get(c) for c in _INBOX_COLS}
        if values["status"] in OPEN_INBOX:
            values["status"] = FILED
        cur = conn.execute(f"INSERT INTO work_inbox (list_key, item_ids, {', '.join(values)}) VALUES (?, ?, {', '.join('?' * len(values))})",
                           (list_key, json.dumps(linked), *values.values()))
        entry_map[entry["id"]] = int(cur.lastrowid)
    for item in data.get("items", []):
        if item.get("inbox_id") in entry_map and item["id"] in item_map:
            conn.execute("UPDATE work_items SET inbox_id = ? WHERE id = ?", (entry_map[item["inbox_id"]], item_map[item["id"]]))
    return list(entry_map.values())


def undo(conn: sqlite3.Connection, item_ids: Iterable[int], inbox_ids: Iterable[int]) -> None:
    tables = _tables(conn)
    for item_id in item_ids:
        if "work_card_events" in tables:
            conn.execute(f"DELETE FROM work_card_events WHERE item_id = ? AND kind = '{STATE_KIND}'", (item_id,))
        for table in ("work_item_lineage", "work_blockers"):
            if table in tables:
                conn.execute(f"DELETE FROM {table} WHERE item_id = ?", (item_id,))
    if "work_inbox" in tables:
        for entry_id in inbox_ids:
            conn.execute("DELETE FROM work_inbox WHERE id = ?", (entry_id,))
