
from __future__ import annotations

import json
import sqlite3
from typing import NamedTuple, Optional

from src.cplugs.huddle import files, rich_ask

FREEFORM = "freeform"


def newest_open_typed(conn: sqlite3.Connection, item_id: int) -> Optional[int]:
    row = conn.execute("SELECT id, parts FROM work_messages WHERE item_id = ? AND kind = 'question' AND answered = 0 "
                       "ORDER BY id DESC LIMIT 1", (item_id,)).fetchone()
    return int(row["id"]) if row is not None and rich_ask.is_typed(row["parts"]) else None


class Provisional(NamedTuple):

    parts: str
    asker: str


def answer(conn: sqlite3.Connection, item_id: int, seq: int, parts: str) -> Provisional:
    question = newest_open_typed(conn, item_id)
    if question is None:
        return Provisional(parts, "")
    conn.execute("UPDATE work_messages SET answered = 1, seq = ? WHERE id = ?", (seq, question))
    asked = conn.execute("SELECT author_key FROM work_messages WHERE id = ?", (question,)).fetchone()
    stored = {"v": rich_ask.VERSION, "answers_to": question, FREEFORM: True}
    attached = files.entries_of(parts)
    if attached:
        stored["files"] = attached
    return Provisional(json.dumps(stored, ensure_ascii=False), asked[0] if asked and asked[0] else "")


__all__ = ["FREEFORM", "Provisional", "answer", "newest_open_typed"]
