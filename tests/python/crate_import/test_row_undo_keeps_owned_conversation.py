from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.crate_import import row_journal as rj
from src.core.crate_import.row_undo import WHY_CONVERSATION_OWNED, plan_store

SESSIONS = {"pk": ["id"], "cols": ["id", "claude_session_uuid"], "ins": [], "rev": []}
INDEX = {"pk": ["conversation_id"], "cols": ["conversation_id", "title"], "ins": [], "rev": []}


def _db(tmp_path: Path, owner_uuid: str | None) -> Path:
    path = tmp_path / "c.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, claude_session_uuid TEXT)")
    conn.execute("CREATE TABLE conversation_index (conversation_id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO sessions VALUES (1, NULL), (2, ?)", (owner_uuid,))
    conn.execute("INSERT INTO conversation_index VALUES ('c1', 'imported')")
    conn.commit()
    conn.close()
    return path


def _tables() -> dict:
    sessions = {**SESSIONS, "ins": [[[1], rj.row_hash([1, "c1"])]]}
    index = {**INDEX, "ins": [[["c1"], rj.row_hash(["c1", "imported"])]]}
    return {"sessions": sessions, "conversation_index": index}


def test_index_row_of_a_conversation_a_live_row_owns_is_kept(tmp_path: Path) -> None:
    plan = plan_store(_db(tmp_path, "c1"), "cloude.db", _tables())
    assert "conversation_index" not in plan.deletes
    assert {"what": "conversation_index row c1", "why": WHY_CONVERSATION_OWNED} in plan.kept


def test_index_row_nobody_owns_is_still_deleted(tmp_path: Path) -> None:
    plan = plan_store(_db(tmp_path, None), "cloude.db", _tables())
    assert plan.deletes["conversation_index"] == [["c1"]]
