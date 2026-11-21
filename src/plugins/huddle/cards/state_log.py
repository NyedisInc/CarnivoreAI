
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

KIND = "state"
NOT_STATE = f"kind != '{KIND}'"


def write(conn: sqlite3.Connection, item_id: int, list_key: str, from_state: str, to_state: str, *, by: str, now: float, detail: str = "") -> None:
    conn.execute("INSERT INTO work_card_events (item_id, list_key, at, kind, from_col, to_col, by, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (item_id, list_key, now, KIND, from_state, to_state, by, detail))


def for_item(conn: sqlite3.Connection, item_id: int) -> List[Dict[str, Any]]:
    return [{"id": r["id"], "item": r["item_id"], "list": r["list_key"], "at": r["at"], "from": r["from_col"], "to": r["to_col"],
             "by": r["by"], "detail": r["detail"]}
            for r in conn.execute("SELECT * FROM work_card_events WHERE item_id = ? AND kind = ? ORDER BY id", (item_id, KIND))]


def newest(conn: sqlite3.Connection, item_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT from_col AS from_state, to_col AS to_state, by, detail FROM work_card_events WHERE item_id = ? AND kind = ? "
                        "ORDER BY id DESC LIMIT 1", (item_id, KIND)).fetchone()


def purge(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM work_card_events WHERE item_id = ? AND kind = ?", (item_id, KIND))
