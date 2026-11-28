from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest

from src.core.db import transaction
from src.core.db_models import SESSION_ORIGIN_ADOPTED
from src.core.session_claude_correlate_bind import BIND_UNRESOLVED, bind_correlated_uuid
from src.core.session_conversation_rebind import TakeFrom, _row_to_take_from
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, listing_of, migrated_connection, session_row

EPOCH = 1_800_000_000
UUID = "52c8040d-0000-4000-8000-000000000001"
LIVE = "cloude_live3262"


@pytest.fixture()
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(migrated_connection(tmp_path)) as connection:
        yield connection


def _seed(conn: sqlite3.Connection, **holder_cols: Any) -> int:
    with transaction(conn):
        record_instance(conn, socket=TEST_SOCKET, name=LIVE, epoch=EPOCH, origin=SESSION_ORIGIN_ADOPTED)
        holder = record_instance(conn, socket=TEST_SOCKET, name="holder3262", epoch=EPOCH + 1,
                                 origin=SESSION_ORIGIN_ADOPTED)
        bind_correlated_uuid(conn, socket=TEST_SOCKET, name="holder3262", epoch=EPOCH + 1, claude_uuid=UUID)
        sets = ", ".join(f"{k} = ?" for k in holder_cols)
        conn.execute(f"UPDATE sessions SET {sets} WHERE id = ?", (*holder_cols.values(), holder.session_id))
    return holder.session_id


def _taker(conn: sqlite3.Connection) -> Optional[TakeFrom]:
    return _row_to_take_from(
        conn, session_id="ses_1", socket=TEST_SOCKET, tmux_name=LIVE, epoch=EPOCH, registry_uuid=UUID,
        listing_reader=lambda: listing_of([]), pane_probe=None,
    )


def test_archived_holder_without_tmux_identity_gives_up_the_conversation(conn: sqlite3.Connection) -> None:
    holder_id = _seed(conn, tmux_name=None, tmux_created_epoch=None, tmux_session_id=None,
                      lifecycle="stopped", archived_at="2026-09-08T00:00:00Z")
    assert _taker(conn) == TakeFrom(holder_id, True)
    with transaction(conn):
        bind_correlated_uuid(conn, socket=TEST_SOCKET, name=LIVE, epoch=EPOCH, claude_uuid=UUID,
                                      takes_from_row_id=holder_id)
    assert session_row(conn, LIVE)["claude_session_uuid"] == UUID
    row = conn.execute("SELECT claude_session_uuid FROM sessions WHERE id = ?", (holder_id,)).fetchone()
    assert row[0] is None


def test_running_holder_still_refuses(conn: sqlite3.Connection) -> None:
    _seed(conn, tmux_name=None, tmux_created_epoch=None, lifecycle="running",
          archived_at="2026-09-08T00:00:00Z")
    assert _taker(conn) is None


def test_unarchived_holder_without_tmux_name_still_refuses(conn: sqlite3.Connection) -> None:
    _seed(conn, tmux_name=None, tmux_created_epoch=None, lifecycle="stopped", archived_at=None)
    assert _taker(conn) is None


def test_holder_with_a_tmux_name_still_goes_through_the_measurement(conn: sqlite3.Connection) -> None:
    _seed(conn, tmux_name="holder3262", lifecycle="stopped", archived_at="2026-09-08T00:00:00Z")
    assert _row_to_take_from(
        conn, session_id="ses_1", socket=TEST_SOCKET, tmux_name=LIVE, epoch=EPOCH, registry_uuid=UUID,
        listing_reader=lambda: listing_of([{"name": "holder3262"}]), pane_probe=lambda *a: False,
    ) is None


def test_recreate_in_flight_on_the_holder_steps_aside(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core import restart_inflight

    holder_id = _seed(conn, tmux_name=None, tmux_created_epoch=None, lifecycle="stopped",
                      archived_at="2026-09-08T00:00:00Z")
    key = conn.execute("SELECT session_uuid FROM sessions WHERE id = ?", (holder_id,)).fetchone()[0]
    monkeypatch.setattr(restart_inflight, "in_flight", lambda k: k == key)
    assert _taker(conn) is None


def test_no_tmux_listing_is_read_for_an_archived_holder(conn: sqlite3.Connection) -> None:
    _seed(conn, tmux_name=None, tmux_created_epoch=None, lifecycle="stopped", archived_at="2026-09-08T00:00:00Z")

    def boom() -> None:
        raise AssertionError("the tmux socket was listed")

    assert _row_to_take_from(conn, session_id="ses_1", socket=TEST_SOCKET, tmux_name=LIVE, epoch=EPOCH,
                             registry_uuid=UUID, listing_reader=boom, pane_probe=None) is not None


def test_a_holder_that_changed_after_the_measurement_is_not_released(conn: sqlite3.Connection) -> None:
    holder_id = _seed(conn, tmux_name=None, tmux_created_epoch=None, lifecycle="stopped",
                      archived_at="2026-09-08T00:00:00Z")
    conn.execute("UPDATE sessions SET tmux_name = 'back_again' WHERE id = ?", (holder_id,))
    with transaction(conn):
        result = bind_correlated_uuid(conn, socket=TEST_SOCKET, name=LIVE, epoch=EPOCH, claude_uuid=UUID,
                                      takes_from_row_id=holder_id, release_requires_retired_no_pane=True)
    assert result.outcome == BIND_UNRESOLVED
    held = conn.execute("SELECT claude_session_uuid FROM sessions WHERE id = ?", (holder_id,)).fetchone()[0]
    assert held == UUID
    assert session_row(conn, LIVE)["claude_session_uuid"] is None
