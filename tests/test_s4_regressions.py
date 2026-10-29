
from __future__ import annotations

import json
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
from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_identity import (
    RECORD_MERGED,
    RECORD_REFUSED_INSTANCE_MISMATCH,
    adopt_instance,
    record_instance,
)
from src.core.session_store import count_sessions, list_sessions


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


def _live(name, epoch, session_id=None):
    row = {"name": name, "created_at_epoch": epoch, "window_count": 1}
    if session_id is not None:
        row["tmux_session_id"] = session_id
    return row




def test_a_DIFFERENT_session_id_on_a_RUNNING_row_is_refused(conn):
    with transaction(conn):
        record_instance(
            conn, socket="cloude", name="cloude_work", epoch=1755000000,
            origin=SESSION_ORIGIN_CREATED,
            lifecycle=SESSION_LIFECYCLE_RUNNING,
            session_id="$3",
        )
        adopt_instance(
            conn, socket="cloude", name="cloude_work", epoch=1755000000,
            now="2026-08-18T00:00:00Z",
        )
    before = list_sessions(conn)[0]
    assert before["origin"] == SESSION_ORIGIN_ADOPTED
    assert before["tmux_session_id"] == "$3"

    with transaction(conn):
        result = record_instance(
            conn, socket="cloude", name="cloude_work", epoch=1755000000,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle=SESSION_LIFECYCLE_RUNNING,
            session_id="$9",
        )

    assert result.outcome == RECORD_REFUSED_INSTANCE_MISMATCH
    assert result.refused is True
    assert result.detail and "$9" in result.detail and "$3" in result.detail

    after = list_sessions(conn)[0]
    assert after["session_uuid"] == before["session_uuid"]
    assert after["origin"] == SESSION_ORIGIN_ADOPTED
    assert after["adopted_at"] == "2026-08-18T00:00:00Z"
    assert after["tmux_session_id"] == "$3", "the stranger overwrote the id"
    assert count_sessions(conn) == 1


def test_the_SAME_session_id_still_merges_because_it_is_the_same_session(conn):
    with transaction(conn):
        record_instance(
            conn, socket="cloude", name="a", epoch=1000,
            origin=SESSION_ORIGIN_CREATED, session_id="$1",
        )
    with transaction(conn):
        result = record_instance(
            conn, socket="cloude", name="a", epoch=1000,
            origin=SESSION_ORIGIN_OBSERVED, session_id="$1",
        )
    assert result.outcome == RECORD_MERGED
    assert list_sessions(conn)[0]["origin"] == SESSION_ORIGIN_CREATED


def test_a_MISSING_session_id_never_manufactures_a_refusal(conn):
    with transaction(conn):
        record_instance(
            conn, socket="cloude", name="a", epoch=1000,
            origin=SESSION_ORIGIN_CREATED,
        )
    assert list_sessions(conn)[0]["tmux_session_id"] is None

    with transaction(conn):
        result = record_instance(
            conn, socket="cloude", name="a", epoch=1000,
            origin=SESSION_ORIGIN_OBSERVED, session_id="$4",
        )
    assert result.outcome == RECORD_MERGED
    assert list_sessions(conn)[0]["tmux_session_id"] == "$4"

    with transaction(conn):
        again = record_instance(
            conn, socket="cloude", name="a", epoch=1000,
            origin=SESSION_ORIGIN_OBSERVED,
        )
    assert again.outcome == RECORD_MERGED
    assert list_sessions(conn)[0]["tmux_session_id"] == "$4", (
        "a caller with no id overwrote the recorded one, destroying the "
        "evidence the mismatch refusal depends on"
    )


def test_adopt_instance_REFUSES_a_stopped_row(conn):
    with transaction(conn):
        record_instance(
            conn, socket="cloude", name="dead", epoch=1755000000,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle=SESSION_LIFECYCLE_STOPPED,
        )
        claimed = adopt_instance(
            conn, socket="cloude", name="dead", epoch=1755000000
        )
    assert claimed is False
    row = list_sessions(conn)[0]
    assert row["origin"] == SESSION_ORIGIN_OBSERVED
    assert row["adopted_at"] is None


def test_adopt_instance_still_claims_a_RUNNING_row(conn):
    with transaction(conn):
        record_instance(
            conn, socket="cloude", name="live", epoch=1000,
            origin=SESSION_ORIGIN_OBSERVED,
            lifecycle=SESSION_LIFECYCLE_RUNNING,
        )
        assert adopt_instance(
            conn, socket="cloude", name="live", epoch=1000
        ) is True
    assert list_sessions(conn)[0]["origin"] == SESSION_ORIGIN_ADOPTED


def test_adopt_instance_on_an_ABSENT_row_is_still_False(conn):
    with transaction(conn):
        assert adopt_instance(
            conn, socket="cloude", name="nope", epoch=1
        ) is False
    assert count_sessions(conn) == 0


def test_the_MANAGER_never_fabricates_a_wildcard_epoch(monkeypatch):
    from src.core.session_manager import SessionManager
    from src.core.sessions.owned_tmux_ledger import OwnedTmuxLedger

    manager = SessionManager()
    manager._owned.names = {"legacy_name", "another"}
    monkeypatch.setattr(
        OwnedTmuxLedger,
        "instances_from_db",
        lambda self: {("stored", 1000)},
    )

    instances = manager._owned.instances()
    assert instances == {("stored", 1000)}
    assert all(
        epoch is not None for _name, epoch in instances
    ), "a None epoch was fabricated; that is the wildcard, rebuilt"
    assert not any(
        name in manager._owned.names for name, _epoch in instances
    ), "legacy names leaked into the INSTANCE set instead of owned_names"


def test_the_manager_reports_NO_OPINION_distinctly_from_OWNS_NOTHING(monkeypatch):
    from src.core.session_manager import SessionManager
    from src.core.sessions.owned_tmux_ledger import OwnedTmuxLedger

    manager = SessionManager()
    manager._owned.names = {"legacy_name"}

    monkeypatch.setattr(
        OwnedTmuxLedger, "instances_from_db", lambda self: None
    )
    assert manager._owned.instances() is None

    monkeypatch.setattr(
        OwnedTmuxLedger, "instances_from_db", lambda self: set()
    )
    assert manager._owned.instances() == set()


