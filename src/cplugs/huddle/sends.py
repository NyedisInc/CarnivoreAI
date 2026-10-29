
from __future__ import annotations

import sqlite3
from typing import Dict, Iterable, Mapping


def sendable_sql(table: str = "") -> str:
    return f"{table + '.' if table else ''}swarm_ref = ''"


def sendable(row: Mapping) -> bool:
    return not (row["swarm_ref"] if "swarm_ref" in row.keys() else "")


def stamp_joe(conn: sqlite3.Connection, item_ids: Iterable[int], seq: int) -> None:
    conn.executemany("UPDATE work_items SET joe_seq = ? WHERE id = ?", [(seq, i) for i in item_ids])


def untold_lists(conn: sqlite3.Connection) -> Dict[str, bool]:
    rows = conn.execute(
        f"SELECT i.list_key FROM work_items i LEFT JOIN work_sends t ON t.list_key = i.list_key WHERE {sendable_sql('i')} AND i.deleted = 0 "
        "GROUP BY i.list_key HAVING MAX(i.joe_seq) > COALESCE(MAX(t.cursor), 0)")
    return {r[0]: True for r in rows}


def record_send(conn: sqlite3.Connection, list_keys: Iterable[str], cursor: int, target: str = "") -> None:
    conn.executemany(
        "INSERT INTO work_sends (list_key, cursor, target) VALUES (?, ?, ?) ON CONFLICT(list_key) DO UPDATE SET "
        "cursor = MAX(cursor, excluded.cursor), target = CASE WHEN excluded.target = '' THEN target ELSE excluded.target END",
        [(k, cursor, target) for k in list_keys])


def targets(conn: sqlite3.Connection, list_keys: Iterable[str]) -> Dict[str, str]:
    keys = list(list_keys)
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    return {r[0]: r[1] for r in conn.execute(
        f"SELECT list_key, target FROM work_sends WHERE target != '' AND list_key IN ({marks})", keys)}
