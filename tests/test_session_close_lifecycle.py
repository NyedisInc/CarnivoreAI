
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.session_close_lifecycle import LIFECYCLE_SOURCE_CLOSED, mark_closed
from src.core.session_store import list_sessions
from src.core.trail_entry import utc_now


@pytest.fixture
def conn(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ensure_db_migrated(state, 4, "0.8.2")
    c = connect(db_path_for(state))
    yield c
    c.close()


def _insert(conn, **overrides):
    row = {
        "session_uuid": "s-1",
        "origin": "created",
        "tmux_socket": "cloude",
        "tmux_name": "cloude_CloudeCode",
        "tmux_created_epoch": 1788787880,
        "working_dir": "/Users/x/proj",
        "lifecycle": "running",
        "activity_state": "working",
        "activity_state_at": utc_now(),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    row.update(overrides)
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with transaction(conn):
        cur = conn.execute(
            f"INSERT INTO sessions ({cols}) VALUES ({marks})", list(row.values())
        )
    return int(cur.lastrowid)


def _row(conn, row_id):
    return dict(
        conn.execute("SELECT * FROM sessions WHERE id = ?", (row_id,)).fetchone()
    )


def test_close_moves_the_row_into_recent_immediately(conn):
    row_id = _insert(conn)

    before = list_sessions(conn, lifecycle="stopped", include_archived=False)
    assert [r["id"] for r in before] == []

    moved = mark_closed(conn, socket="cloude", name="cloude_CloudeCode")
    conn.commit()

    assert moved == 1
    after = list_sessions(conn, lifecycle="stopped", include_archived=False)
    assert [r["id"] for r in after] == [row_id], (
        "the closed session did not reach RECENT; it is in no group the "
        "user can see"
    )
    row = _row(conn, row_id)
    assert row["lifecycle_source"] == LIFECYCLE_SOURCE_CLOSED
    assert row["activity_state"] is None


def test_close_never_writes_archived_at(conn):
    row_id = _insert(conn)

    mark_closed(conn, socket="cloude", name="cloude_CloudeCode")
    conn.commit()

    assert _row(conn, row_id)["archived_at"] is None


def test_close_leaves_a_lineage_row_alone(conn):
    anchor = _insert(conn, session_uuid="anchor")
    lineage = _insert(
        conn,
        session_uuid="lineage",
        tmux_created_epoch=None,
        parent_session_id=anchor,
        lifecycle="running",
    )

    moved = mark_closed(conn, socket="cloude", name="cloude_CloudeCode")
    conn.commit()

    assert moved == 1
    assert _row(conn, lineage)["lifecycle"] == "running"


def test_close_of_an_unknown_tmux_name_reports_zero_not_an_error(conn):
    _insert(conn)

    assert mark_closed(conn, socket="cloude", name="cloude_somebody_else") == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    )
