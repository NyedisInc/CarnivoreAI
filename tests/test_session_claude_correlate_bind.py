
from __future__ import annotations

import os
import sys
from contextlib import closing
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
from src.core.db import transaction
from src.core.db_models import (
    SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
    SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV,
    SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
    SESSION_ORIGIN_ADOPTED,
)
from src.core.session_claude_correlate_bind import (
    BIND_ALREADY_KNOWN,
    BIND_BOUND,
    BIND_REBOUND,
    BIND_UNRESOLVED,
    bind_correlated_uuid,
)
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, migrated_connection, session_row

NAME = "cloudes7test_a"
EPOCH = 1_800_000_000
UUID_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture()
def conn(tmp_path):
    with closing(migrated_connection(tmp_path)) as connection:
        yield connection


@pytest.fixture()
def anchor(conn):
    with transaction(conn):
        result = record_instance(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            origin=SESSION_ORIGIN_ADOPTED,
            working_dir="/tmp/proj",
        )
    return result.session_id


def test_decisive_bind_records_uuid_with_correlated_provenance(conn, anchor):
    with transaction(conn):
        result = bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_A
        )
    assert result.outcome == BIND_BOUND
    assert result.wrote
    assert result.row_id == anchor

    row = session_row(conn, NAME)
    assert row["claude_session_uuid"] == UUID_A
    assert row["claude_session_uuid_source"] == SESSION_CLAUDE_UUID_SOURCE_CORRELATED


def test_uuid_already_on_another_row_does_not_raise_or_duplicate(conn, anchor):
    other_name = "cloudes7test_other"
    with transaction(conn):
        other = record_instance(
            conn,
            socket=TEST_SOCKET,
            name=other_name,
            epoch=EPOCH + 1,
            origin=SESSION_ORIGIN_ADOPTED,
        )
        first_bind = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=other_name,
            epoch=EPOCH + 1,
            claude_uuid=UUID_A,
        )
    assert first_bind.outcome == BIND_BOUND

    with transaction(conn):
        second_bind = bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_A
        )
    assert second_bind.outcome == BIND_ALREADY_KNOWN
    assert not second_bind.wrote
    assert second_bind.row_id == other.session_id

    anchor_row = session_row(conn, NAME)
    assert anchor_row["claude_session_uuid"] is None

    all_uuids = [
        row["claude_session_uuid"]
        for row in conn.execute(
            "SELECT claude_session_uuid FROM sessions "
            "WHERE claude_session_uuid IS NOT NULL"
        ).fetchall()
    ]
    assert all_uuids == [UUID_A]


def test_archived_row_is_never_un_archived_by_a_bind(conn, anchor):
    stamp = "2027-01-01T00:00:00Z"
    with transaction(conn):
        conn.execute(
            "UPDATE sessions SET archived_at = ? WHERE id = ?", (stamp, anchor)
        )

    with transaction(conn):
        result = bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_A
        )
    assert result.outcome == BIND_BOUND

    row = session_row(conn, NAME)
    assert row["claude_session_uuid"] == UUID_A
    assert row["archived_at"] == stamp


def test_no_anchor_row_is_unresolved_not_a_crash(conn):
    with transaction(conn):
        result = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name="cloudes7test_ghost",
            epoch=999,
            claude_uuid=UUID_A,
        )
    assert result.outcome == BIND_UNRESOLVED
    assert not result.wrote


def test_anchor_with_a_different_uuid_already_set_is_left_alone(conn, anchor):
    with transaction(conn):
        conn.execute(
            "UPDATE sessions SET claude_session_uuid = ?, "
            "claude_session_uuid_source = 'hook' WHERE id = ?",
            (UUID_A, anchor),
        )

    with transaction(conn):
        result = bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_B
        )
    assert result.outcome == BIND_UNRESOLVED
    assert not result.wrote

    row = session_row(conn, NAME)
    assert row["claude_session_uuid"] == UUID_A
    assert row["claude_session_uuid_source"] == "hook"


def test_argv_bind_records_the_stronger_correlated_argv_provenance(conn, anchor):
    with transaction(conn):
        result = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            claude_uuid=UUID_A,
            source=SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV,
        )
    assert result.outcome == BIND_BOUND
    row = session_row(conn, NAME)
    assert row["claude_session_uuid"] == UUID_A
    assert row["claude_session_uuid_source"] == SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV


def test_argv_uuid_already_on_another_row_does_not_raise_or_duplicate(conn, anchor):
    other_name = "cloudes7test_argv_other"
    with transaction(conn):
        other = record_instance(
            conn,
            socket=TEST_SOCKET,
            name=other_name,
            epoch=EPOCH + 1,
            origin=SESSION_ORIGIN_ADOPTED,
        )
        first = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=other_name,
            epoch=EPOCH + 1,
            claude_uuid=UUID_A,
            source=SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV,
        )
    assert first.outcome == BIND_BOUND

    with transaction(conn):
        second = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            claude_uuid=UUID_A,
            source=SESSION_CLAUDE_UUID_SOURCE_CORRELATED_ARGV,
        )
    assert second.outcome == BIND_ALREADY_KNOWN
    assert not second.wrote
    assert second.row_id == other.session_id
    assert session_row(conn, NAME)["claude_session_uuid"] is None


def test_none_epoch_is_unresolved(conn):
    with transaction(conn):
        result = bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=None, claude_uuid=UUID_A
        )
    assert result.outcome == BIND_UNRESOLVED
    assert not result.wrote


def test_a_rebind_naming_the_measured_incumbent_replaces_it(conn, anchor):
    with transaction(conn):
        bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_A
        )

    with transaction(conn):
        result = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            claude_uuid=UUID_B,
            source=SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
            replaces_uuid=UUID_A,
        )

    assert result.outcome == BIND_REBOUND
    assert result.wrote
    row = session_row(conn, NAME)
    assert row["claude_session_uuid"] == UUID_B
    assert row["claude_session_uuid_source"] == SESSION_CLAUDE_UUID_SOURCE_REGISTRY


def test_a_rebind_naming_the_wrong_incumbent_is_refused(conn, anchor):
    other = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    with transaction(conn):
        bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_A
        )

    with transaction(conn):
        result = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            claude_uuid=UUID_B,
            source=SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
            replaces_uuid=other,
        )

    assert result.outcome == BIND_UNRESOLVED
    assert not result.wrote
    assert session_row(conn, NAME)["claude_session_uuid"] == UUID_A


def test_a_named_holder_row_releases_the_conversation_in_one_statement_pair(
    conn, anchor
):
    holder_name = "cloudes7test_holder"
    with transaction(conn):
        holder = record_instance(
            conn,
            socket=TEST_SOCKET,
            name=holder_name,
            epoch=EPOCH + 2,
            origin=SESSION_ORIGIN_ADOPTED,
        )
        bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=holder_name,
            epoch=EPOCH + 2,
            claude_uuid=UUID_B,
        )
        bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_A
        )

    with transaction(conn):
        result = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            claude_uuid=UUID_B,
            source=SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
            replaces_uuid=UUID_A,
            takes_from_row_id=holder.session_id,
        )

    assert result.outcome == BIND_REBOUND
    assert result.wrote
    assert result.row_id == anchor
    assert result.took_from_row_id == holder.session_id

    assert session_row(conn, NAME)["claude_session_uuid"] == UUID_B
    assert session_row(conn, holder_name)["claude_session_uuid"] is None
    assert session_row(conn, holder_name)["claude_session_uuid_source"] is None
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2


def test_a_holder_row_that_moved_since_the_measurement_is_refused(conn, anchor):
    holder_name = "cloudes7test_holder"
    with transaction(conn):
        record_instance(
            conn,
            socket=TEST_SOCKET,
            name=holder_name,
            epoch=EPOCH + 2,
            origin=SESSION_ORIGIN_ADOPTED,
        )
        bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=holder_name,
            epoch=EPOCH + 2,
            claude_uuid=UUID_B,
        )
        bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_A
        )

    with transaction(conn):
        result = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            claude_uuid=UUID_B,
            source=SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
            replaces_uuid=UUID_A,
            takes_from_row_id=999_999,
        )

    assert result.outcome == BIND_ALREADY_KNOWN
    assert not result.wrote
    assert result.took_from_row_id is None
    assert session_row(conn, NAME)["claude_session_uuid"] == UUID_A
    assert session_row(conn, holder_name)["claude_session_uuid"] == UUID_B


def test_a_takeover_without_a_measured_incumbent_is_still_refused(conn, anchor):
    holder_name = "cloudes7test_holder"
    with transaction(conn):
        holder = record_instance(
            conn,
            socket=TEST_SOCKET,
            name=holder_name,
            epoch=EPOCH + 2,
            origin=SESSION_ORIGIN_ADOPTED,
        )
        bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=holder_name,
            epoch=EPOCH + 2,
            claude_uuid=UUID_B,
        )
        bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_A
        )

    with transaction(conn):
        result = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            claude_uuid=UUID_B,
            source=SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
            takes_from_row_id=holder.session_id,
        )

    assert result.outcome == BIND_UNRESOLVED
    assert not result.wrote
    assert session_row(conn, NAME)["claude_session_uuid"] == UUID_A
    assert session_row(conn, holder_name)["claude_session_uuid"] == UUID_B


def test_a_takeover_naming_the_target_row_itself_changes_nothing(conn, anchor):
    with transaction(conn):
        bind_correlated_uuid(
            conn, socket=TEST_SOCKET, name=NAME, epoch=EPOCH, claude_uuid=UUID_A
        )

    with transaction(conn):
        result = bind_correlated_uuid(
            conn,
            socket=TEST_SOCKET,
            name=NAME,
            epoch=EPOCH,
            claude_uuid=UUID_A,
            source=SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
            replaces_uuid=UUID_A,
            takes_from_row_id=anchor,
        )

    assert result.outcome == BIND_ALREADY_KNOWN
    assert result.took_from_row_id is None
    assert session_row(conn, NAME)["claude_session_uuid"] == UUID_A
