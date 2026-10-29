
from __future__ import annotations

import os
import sqlite3

from src.core.skill_fires import store as store_module
from src.core.skill_fires.store import Cursor, SkillFireStore


def test_many_calls_open_one_connection(tmp_path, monkeypatch):
    opened = []
    real = sqlite3.connect

    def counting(*args, **kwargs):
        opened.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(store_module.sqlite3, "connect", counting)
    store = SkillFireStore(tmp_path / "f.db")
    for _ in range(5):
        store.cursor_for("/t.jsonl")
        store.count("/t.jsonl")
        store.recent("/t.jsonl", limit=1)
    assert len(opened) == 1


def test_a_deleted_file_is_recreated_not_written_into_the_void(tmp_path):
    path = tmp_path / "f.db"
    store = SkillFireStore(path)
    store.apply("/t.jsonl", harness="claude", profile="default", session_key="t",
                cursor=Cursor(10, b"h", 10), fires=[], reset=True)
    assert store.cursor_for("/t.jsonl") == Cursor(10, b"h", 10)
    os.remove(path)
    assert store.cursor_for("/t.jsonl") is None
    store.apply("/t.jsonl", harness="claude", profile="default", session_key="t",
                cursor=Cursor(20, b"h", 20), fires=[], reset=True)
    assert path.exists()
    assert SkillFireStore(path).cursor_for("/t.jsonl") == Cursor(20, b"h", 20)
