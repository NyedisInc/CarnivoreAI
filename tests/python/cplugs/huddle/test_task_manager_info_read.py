
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.cplugs.huddle.store import TaskManagerStore
from src.core.work.ladder import MIGRATIONS, SCHEMA_VERSION
from src.core.work.storage import WorkStorage


def test_a_rung_ten_file_keeps_seen_infos_read_and_unseen_infos_unread(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:10]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, "
                     "seq, seen_seq, info_seq) VALUES ('all', 'row', 0, 'joe', 'open', 1, 1, 1, 9, 5, 7)")
        for seq, kind in ((3, "info"), (7, "info"), (8, "reply")):
            conn.execute("INSERT INTO messages (item_id, author, kind, text, created_at, seq) VALUES (1, ?, ?, ?, 1, ?)",
                         ("joe" if kind == "reply" else "claude", kind, f"m{seq}", seq))
        conn.execute("PRAGMA user_version = 10")
    item = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None).list_items("all")["items"][0]
    assert SCHEMA_VERSION >= 33
    assert [(m["text"], m["unread"]) for m in item["thread"]] == [("m3", False), ("m7", True), ("m8", False)]
    assert item["info_unread"] == 1 and item["info_unseen"] is True and item["status"] != "info"


def test_a_rung_eleven_file_keeps_seen_looks_read_and_unseen_looks_unread(tmp_path: Path):
    path = tmp_path / "huddle.db"
    with sqlite3.connect(path) as conn:
        for step in MIGRATIONS[:11]:
            conn.executescript(step)
        conn.execute("INSERT INTO items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, "
                     "seq, seen_seq, call_seq) VALUES ('all', 'row', 0, 'joe', 'open', 1, 1, 1, 9, 5, 7)")
        for seq, kind in ((3, "attention"), (7, "attention"), (8, "reply")):
            conn.execute("INSERT INTO messages (item_id, author, kind, text, created_at, seq) VALUES (1, ?, ?, ?, 1, ?)",
                         ("joe" if kind == "reply" else "claude", kind, f"m{seq}", seq))
        conn.execute("PRAGMA user_version = 11")
    item = TaskManagerStore(WorkStorage(path.parent), notify=lambda t: None).list_items("all")["items"][0]
    assert SCHEMA_VERSION >= 33
    assert [(m["text"], m["unread"]) for m in item["thread"]] == [("m3", False), ("m7", True), ("m8", False)]
    assert item["attention_unread"] == 1 and item["attention_unseen"] is True and item["status"] == "open"
