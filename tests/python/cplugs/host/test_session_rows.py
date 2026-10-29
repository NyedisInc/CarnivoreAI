
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.api import peer_auth
from src.core.db import DatastoreUnreadableError
from src.cplugs.host import session_rows
from src.cplugs.sdk.session_rows import SessionRowsUnreadable, StoredRow


@pytest.fixture
def datastore(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "carnivore.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT, project_id INTEGER, archived_at TEXT)")
        conn.executemany("INSERT INTO sessions (session_uuid, project_id, archived_at) VALUES (?, ?, ?)",
                         [("u-omega", 11, None), ("u-old", 7, "2026-10-14T23:00:00Z"), ("u-loose", None, None)])
    monkeypatch.setattr(peer_auth, "open_db", lambda: sqlite3.connect(path))
    return path


def test_each_key_answers_its_row_and_a_key_with_no_row_is_absent(datastore):
    assert session_rows.read(["u-omega", "u-old", "u-loose", "u-deleted"]) == {
        "u-omega": StoredRow(11, False), "u-old": StoredRow(7, True), "u-loose": StoredRow(None, False)}


def test_no_keys_reads_nothing(monkeypatch):
    monkeypatch.setattr(peer_auth, "open_db", lambda: pytest.fail("no keys must not open the datastore"))
    assert session_rows.read([]) == {}


@pytest.mark.parametrize("failure", [DatastoreUnreadableError("carnivore.db does not exist", Path("x")), sqlite3.OperationalError("locked")])
def test_an_unreadable_datastore_raises_never_answers_empty(monkeypatch, failure):
    def broken():
        raise failure

    monkeypatch.setattr(peer_auth, "open_db", broken)
    with pytest.raises(SessionRowsUnreadable):
        session_rows.read(["u-omega"])
