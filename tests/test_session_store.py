
from __future__ import annotations

import os
import sys
from contextlib import closing
from pathlib import Path

import pytest
import structlog

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
    SESSION_ATTRIBUTION_UNKNOWN,
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_LIFECYCLE_UNKNOWN,
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_identity import (
    RECORD_INSERTED,
    RECORD_MERGED,
    RECORD_REFUSED_EPOCH_COLLISION,
    adopt_instance,
    record_instance,
)
from src.core.session_store import (
    count_sessions,
    get_instance,
    is_owned_origin,
    list_sessions,
    needs_attention,
    observed_origin_for,
    owned_instances,
    owned_names,
)

SOCKET = "cloude"


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


def _observe(conn, name, epoch, **kwargs):
    with transaction(conn):
        return record_instance(
            conn,
            socket=SOCKET,
            name=name,
            epoch=epoch,
            origin=kwargs.pop("origin", SESSION_ORIGIN_OBSERVED),
            **kwargs,
        )




def test_the_instance_index_is_exactly_as_designed(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' "
        "AND name='ux_sessions_host_instance'"
    ).fetchone()
    assert row is not None, "the instance identity index does not exist"
    sql = " ".join(str(row[0]).split())
    assert "CREATE UNIQUE INDEX" in sql
    assert "ON sessions (host_key, tmux_socket, tmux_name, tmux_created_epoch)" in sql
    assert (
        "WHERE tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL" in sql
    )


def test_the_index_is_the_thing_that_refuses_a_duplicate_triple(conn):
    import sqlite3

    _observe(conn, "foo", 1000)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(
                "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
                "tmux_created_epoch, origin, created_at, updated_at) "
                "VALUES ('other-uuid', ?, 'foo', 1000, 'observed', 'x', 'x')",
                (SOCKET,),
            )




def test_adopting_the_same_instance_twice_leaves_exactly_one_row(conn):
    _observe(conn, "foo", 1000)
    for _ in range(2):
        with transaction(conn):
            assert adopt_instance(
                conn, socket=SOCKET, name="foo", epoch=1000,
                now="2026-08-18T00:00:00Z",
            )
    assert count_sessions(conn) == 1


def test_adopted_at_is_FIRST_write_wins(conn):
    _observe(conn, "foo", 1000)
    with transaction(conn):
        adopt_instance(
            conn, socket=SOCKET, name="foo", epoch=1000,
            now="2026-08-18T01:00:00Z", working_dir="/first",
        )
    first = get_instance(conn, socket=SOCKET, name="foo", epoch=1000)

    with transaction(conn):
        adopt_instance(
            conn, socket=SOCKET, name="foo", epoch=1000,
            now="2026-08-18T09:30:00Z",
            working_dir="/second",
        )
    second = get_instance(conn, socket=SOCKET, name="foo", epoch=1000)

    assert first["adopted_at"] == "2026-08-18T01:00:00Z"
    assert second["adopted_at"] == first["adopted_at"], (
        "adopted_at moved on the second adopt - that is last-write-wins, "
        "and it silently rewrites when the user claimed this session"
    )
    assert second["working_dir"] == "/second", (
        "the re-probed working directory should update; only the moment "
        "of the claim is immutable"
    )
    assert second["origin"] == SESSION_ORIGIN_ADOPTED


def test_adopting_an_instance_we_have_no_row_for_creates_nothing(conn):
    with transaction(conn):
        assert adopt_instance(
            conn, socket=SOCKET, name="ghost", epoch=1234
        ) is False
    assert count_sessions(conn) == 0




def test_name_reuse_at_a_later_epoch_gets_its_own_row(conn):
    _observe(conn, "foo", 1000)
    with transaction(conn):
        adopt_instance(
            conn, socket=SOCKET, name="foo", epoch=1000,
            now="2026-08-18T01:00:00Z",
        )
    before = get_instance(conn, socket=SOCKET, name="foo", epoch=1000)

    result = _observe(conn, "foo", 2000)
    assert result.outcome == RECORD_INSERTED
    assert count_sessions(conn) == 2

    after = get_instance(conn, socket=SOCKET, name="foo", epoch=1000)
    assert after == before, (
        "the earlier instance's row changed when a new session took its "
        "name; the adoption has been transferred to a stranger's process"
    )
    assert after["origin"] == SESSION_ORIGIN_ADOPTED
    assert after["adopted_at"] == "2026-08-18T01:00:00Z"

    newcomer = get_instance(conn, socket=SOCKET, name="foo", epoch=2000)
    assert newcomer["origin"] == SESSION_ORIGIN_OBSERVED
    assert newcomer["adopted_at"] is None
    assert newcomer["session_uuid"] != before["session_uuid"]


def test_the_reused_name_does_not_inherit_the_owned_badge(conn):
    _observe(conn, "foo", 1000)
    with transaction(conn):
        adopt_instance(conn, socket=SOCKET, name="foo", epoch=1000)
    _observe(conn, "foo", 2000)

    instances = owned_instances(conn, socket=SOCKET)
    assert ("foo", 1000) in instances
    assert ("foo", 2000) not in instances, (
        "the new instance inherited the old one's ownership badge"
    )
    assert owned_names(conn, socket=SOCKET) == {"foo"}




def test_same_epoch_collision_against_a_stopped_row_is_REFUSED(conn):
    _observe(conn, "foo", 1000)
    with transaction(conn):
        adopt_instance(
            conn, socket=SOCKET, name="foo", epoch=1000,
            now="2026-08-18T01:00:00Z",
        )
        conn.execute(
            "UPDATE sessions SET lifecycle = ? WHERE tmux_name = 'foo'",
            (SESSION_LIFECYCLE_STOPPED,),
        )
    before = get_instance(conn, socket=SOCKET, name="foo", epoch=1000)

    result = _observe(conn, "foo", 1000, lifecycle=SESSION_LIFECYCLE_RUNNING)

    assert result.outcome == RECORD_REFUSED_EPOCH_COLLISION
    assert result.refused is True
    assert count_sessions(conn) == 1, "the refusal still wrote a row"
    after = get_instance(conn, socket=SOCKET, name="foo", epoch=1000)
    assert after == before, "the refused merge modified the stored row anyway"
    assert after["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert after["origin"] == SESSION_ORIGIN_ADOPTED
    assert after["adopted_at"] == "2026-08-18T01:00:00Z"


def test_the_refusal_is_LOGGED_and_the_log_names_both_rows(conn):
    _observe(conn, "foo", 1000)
    with transaction(conn):
        adopt_instance(
            conn, socket=SOCKET, name="foo", epoch=1000,
            now="2026-08-18T01:00:00Z",
        )
        conn.execute(
            "UPDATE sessions SET lifecycle = ? WHERE tmux_name = 'foo'",
            (SESSION_LIFECYCLE_STOPPED,),
        )
    stored = get_instance(conn, socket=SOCKET, name="foo", epoch=1000)

    with structlog.testing.capture_logs() as logs:
        _observe(conn, "foo", 1000, origin=SESSION_ORIGIN_CREATED)

    refusals = [
        entry for entry in logs
        if entry.get("event") == "session_instance_epoch_collision_refused"
    ]
    assert len(refusals) == 1, f"expected exactly one refusal log, got {logs}"
    entry = refusals[0]
    assert entry["log_level"] == "warning"

    assert entry["stored_session_id"] == stored["id"]
    assert entry["stored_session_uuid"] == stored["session_uuid"]
    assert entry["stored_origin"] == SESSION_ORIGIN_ADOPTED
    assert entry["stored_adopted_at"] == "2026-08-18T01:00:00Z"
    assert entry["stored_lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert entry["tmux_socket"] == SOCKET
    assert entry["tmux_name"] == "foo"
    assert entry["tmux_created_epoch"] == 1000
    assert entry["incoming_origin"] == SESSION_ORIGIN_CREATED
    assert stored["session_uuid"] in entry["detail"]
    assert "REFUSED" in entry["detail"]


def test_a_live_row_at_the_same_triple_MERGES_and_never_touches_origin(conn):
    _observe(conn, "foo", 1000)
    with transaction(conn):
        adopt_instance(
            conn, socket=SOCKET, name="foo", epoch=1000,
            now="2026-08-18T01:00:00Z",
        )

    result = _observe(conn, "foo", 1000, origin=SESSION_ORIGIN_OBSERVED)

    assert result.outcome == RECORD_MERGED
    assert count_sessions(conn) == 1
    row = get_instance(conn, socket=SOCKET, name="foo", epoch=1000)
    assert row["origin"] == SESSION_ORIGIN_ADOPTED, (
        "an observed sighting demoted an adopted session; origin must be "
        "written once and never recomputed"
    )
    assert row["adopted_at"] == "2026-08-18T01:00:00Z"




def test_both_created_and_adopted_badge_as_ours_observed_does_not():
    assert is_owned_origin(SESSION_ORIGIN_CREATED) is True
    assert is_owned_origin(SESSION_ORIGIN_ADOPTED) is True
    assert is_owned_origin(SESSION_ORIGIN_OBSERVED) is False
    assert is_owned_origin(None) is False, (
        "no row is not the same claim as an unowned row"
    )


def test_import_origin_can_never_be_adopted():
    assert observed_origin_for("a", {"a"}) == SESSION_ORIGIN_CREATED
    assert observed_origin_for("a", set()) == SESSION_ORIGIN_OBSERVED
    for owned in ({"a"}, set(), {"b"}):
        assert observed_origin_for("a", owned) != SESSION_ORIGIN_ADOPTED




def test_unknown_lifecycle_and_unknown_attribution_reach_NEEDS_ATTENTION(conn):
    _observe(conn, "cannot-probe", 1, lifecycle=SESSION_LIFECYCLE_UNKNOWN)
    _observe(
        conn, "no-cwd", 2,
        project_attribution=SESSION_ATTRIBUTION_UNKNOWN,
    )
    _observe(conn, "healthy", 3, project_attribution="none")

    names = {row["tmux_name"] for row in needs_attention(conn)}
    assert names == {"cannot-probe", "no-cwd"}, (
        "'none' means probed-and-matched-nothing, which is a complete "
        "answer and must NOT be in NEEDS ATTENTION"
    )


def test_archiving_never_hides_a_running_session(conn):
    _observe(conn, "live", 1, lifecycle=SESSION_LIFECYCLE_RUNNING)
    with transaction(conn):
        conn.execute(
            "UPDATE sessions SET archived_at = '2026-08-18T00:00:00Z' "
            "WHERE tmux_name = 'live'"
        )
    running = list_sessions(conn, lifecycle=SESSION_LIFECYCLE_RUNNING)
    assert [row["tmux_name"] for row in running] == ["live"]


def test_every_read_is_empty_and_silent_on_a_pre_v2_database(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        with transaction(connection):
            connection.execute("DROP TABLE sessions")
        assert list_sessions(connection) == []
        assert needs_attention(connection) == []
        assert count_sessions(connection) == 0
        assert owned_instances(connection) == set()
        assert owned_names(connection) == set()
        assert get_instance(
            connection, socket=SOCKET, name="foo", epoch=1
        ) is None
        with transaction(connection):
            assert adopt_instance(
                connection, socket=SOCKET, name="foo", epoch=1
            ) is False


def test_record_instance_rejects_an_unknown_column(conn):
    with pytest.raises(ValueError, match="unknown column"):
        _observe(conn, "foo", 1, not_a_column="x")
