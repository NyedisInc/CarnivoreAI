
from __future__ import annotations

from contextlib import closing

import pytest

from src.core import session_store
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
)
from tests.lifecycle_helpers import add_row

ARCHIVED_STAMP = "2026-08-26T00:00:00.000000Z"


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


def _uuids(rows):
    return {r["session_uuid"] for r in rows}


def test_the_arrangement_is_real(conn):
    add_row(conn, uuid="live-deleted", name="cloude_live", epoch=1000,
            lifecycle=SESSION_LIFECYCLE_RUNNING, archived_at=ARCHIVED_STAMP)
    add_row(conn, uuid="ended-deleted", name="cloude_ended", epoch=1001,
            lifecycle=SESSION_LIFECYCLE_STOPPED, archived_at=ARCHIVED_STAMP)
    everything = session_store.list_sessions(conn)
    assert _uuids(everything) == {"live-deleted", "ended-deleted"}


def test_a_running_session_survives_being_deleted(conn):
    add_row(conn, uuid="live-deleted", name="cloude_live", epoch=1000,
            lifecycle=SESSION_LIFECYCLE_RUNNING, archived_at=ARCHIVED_STAMP)
    running = session_store.list_sessions(
        conn, lifecycle=SESSION_LIFECYCLE_RUNNING)
    assert "live-deleted" in _uuids(running), (
        "A running session vanished from the RUNNING listing because it was "
        "deleted. archived_at means 'off my screen', not 'not running'. "
        "Filtering it here leaves a live agent with no control surface in "
        "the app at all - unseeable and unkillable except from a terminal."
    )


def test_the_same_query_is_capable_of_excluding_the_row(conn):
    add_row(conn, uuid="live-deleted", name="cloude_live", epoch=1000,
            lifecycle=SESSION_LIFECYCLE_RUNNING, archived_at=ARCHIVED_STAMP)
    included = session_store.list_sessions(
        conn, lifecycle=SESSION_LIFECYCLE_RUNNING, include_archived=True)
    excluded = session_store.list_sessions(
        conn, lifecycle=SESSION_LIFECYCLE_RUNNING, include_archived=False)
    assert "live-deleted" in _uuids(included)
    assert "live-deleted" not in _uuids(excluded), (
        "list_sessions cannot exclude an archived row at all, so the "
        "inclusion assertion in this module proves nothing."
    )


def test_the_stored_listing_still_hides_it(conn):
    add_row(conn, uuid="live-deleted", name="cloude_live", epoch=1000,
            lifecycle=SESSION_LIFECYCLE_RUNNING, archived_at=ARCHIVED_STAMP)
    assert "live-deleted" not in _uuids(session_store.listable_sessions(conn)), (
        "listable_sessions must keep excluding archived rows - that is what "
        "makes the live listing's inclusion a deliberate difference rather "
        "than the column being ignored everywhere."
    )


def test_deleting_is_not_killing(conn):
    add_row(conn, uuid="live", name="cloude_live", epoch=1000,
            lifecycle=SESSION_LIFECYCLE_RUNNING)
    assert session_store.archive_session(conn, "live") is True
    row = next(r for r in session_store.list_sessions(conn)
               if r["session_uuid"] == "live")
    assert row["archived_at"] is not None, "the delete did not record itself"
    assert row["lifecycle"] == SESSION_LIFECYCLE_RUNNING, (
        "deleting a row changed the session's lifecycle. It must not: the "
        "process is still running and the next probe is what decides that."
    )


def test_the_attachable_probe_cannot_consult_the_database_at_all():
    import inspect

    from src.core import tmux_listing

    source = inspect.getsource(tmux_listing)
    for forbidden in ("archived_at", "session_store", "sqlite3"):
        assert forbidden not in source, (
            f"tmux_listing now references {forbidden!r}. The live listing is "
            "a process probe; giving it database state is how a running "
            "session becomes hideable."
        )
