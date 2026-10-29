
from __future__ import annotations

import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.session_store import list_sessions, listable_sessions

SOCKET = "cloude"


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


def _insert(conn, uuid, *, name=None, epoch=None, parent=None, fork_kind=None):
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
            "tmux_created_epoch, parent_session_id, fork_kind, origin, "
            "lifecycle, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'created', 'running', 'x', 'x')",
            (uuid, SOCKET, name, epoch, parent, fork_kind),
        )
        return int(cur.lastrowid)


def _listed(conn):
    return {row["session_uuid"] for row in listable_sessions(conn)}




def test_an_ordinary_tmux_session_is_listed(conn):
    _insert(conn, "plain", name="work", epoch=1000)
    assert _listed(conn) == {"plain"}


def test_an_imported_stopped_session_is_listed(conn):
    _insert(conn, "imported", name="old-work", epoch=None)
    assert _listed(conn) == {"imported"}


def test_a_past_claude_conversation_is_not_listed(conn):
    anchor = _insert(conn, "anchor", name="work", epoch=1000)
    _insert(conn, "convo", name="work", epoch=None, parent=anchor,
            fork_kind="fork")
    assert _listed(conn) == {"anchor"}


def test_a_gui_fork_is_listed_even_though_it_has_a_parent(conn):
    parent = _insert(conn, "parent", name="work", epoch=1000)
    _insert(conn, "forked", name="work(fork)", epoch=2000, parent=parent,
            fork_kind="fork")
    assert _listed(conn) == {"parent", "forked"}




def test_forking_leaves_the_parent_row_byte_identical(conn):
    parent = _insert(conn, "parent", name="work", epoch=1000)
    before = dict(
        conn.execute("SELECT * FROM sessions WHERE id = ?", (parent,)).fetchone()
    )

    _insert(conn, "forked", name="work(fork)", epoch=2000, parent=parent,
            fork_kind="fork")

    after = dict(
        conn.execute("SELECT * FROM sessions WHERE id = ?", (parent,)).fetchone()
    )
    assert after == before, "forking mutated the parent row"
    assert after["archived_at"] is None
    assert after["lifecycle"] == "running"


def test_the_parent_can_be_forked_again(conn):
    parent = _insert(conn, "parent", name="work", epoch=1000)
    _insert(conn, "fork1", name="work(fork)", epoch=2000, parent=parent,
            fork_kind="fork")
    _insert(conn, "fork2", name="work(fork)(fork)", epoch=3000, parent=parent,
            fork_kind="fork")
    assert _listed(conn) == {"parent", "fork1", "fork2"}




def test_include_lineage_still_returns_conversation_rows(conn):
    anchor = _insert(conn, "anchor", name="work", epoch=1000)
    _insert(conn, "convo", name="work", epoch=None, parent=anchor,
            fork_kind="fork")
    rows = list_sessions(conn, include_lineage=True)
    assert {r["session_uuid"] for r in rows} == {"anchor", "convo"}
