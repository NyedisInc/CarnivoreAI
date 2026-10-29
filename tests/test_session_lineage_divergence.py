
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
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import SESSION_ORIGIN_ADOPTED
from src.core.session_identity import record_instance
from src.core.session_lineage import (
    LINEAGE_BOUND,
    LINEAGE_CONTINUED,
    LINEAGE_FORKED,
    LINEAGE_NO_WRITE,
    LINEAGE_SIBLING,
    record_claude_session,
)
from src.core.session_lineage_divergence import (
    DIVERGENCE_IN_PROCESS_FORK,
    DIVERGENCE_SIBLING_PROCESS,
    DIVERGENCE_SOURCE_UNRECOGNISED,
    IN_PROCESS_TRANSITION_SOURCES,
    PROCESS_BOOT_SOURCES,
    classify_uuid_divergence,
    mints_a_row,
)
from src.core.session_store import get_instance, list_sessions

SOCKET = "cloude"
NAME = "cloude_Agent_-_Cloude_Code"
EPOCH = 1_788_813_811

PANE_UUID = "deab833f-234e-44d2-be54-ddaf69c8db4b"
SIBLING_UUID = "e51254a9-f3c8-452a-8e03-007f28fbd995"


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


@pytest.fixture()
def pane(conn):
    with transaction(conn):
        result = record_instance(
            conn,
            socket=SOCKET,
            name=NAME,
            epoch=EPOCH,
            origin=SESSION_ORIGIN_ADOPTED,
            working_dir="/tmp/proj",
        )
    _record(conn, PANE_UUID, "startup")
    return result.session_id


def _record(conn, claude_uuid, source, **kwargs):
    with transaction(conn):
        return record_claude_session(
            conn,
            socket=kwargs.pop("socket", SOCKET),
            name=kwargs.pop("name", NAME),
            epoch=kwargs.pop("epoch", EPOCH),
            claude_uuid=claude_uuid,
            source=source,
            **kwargs,
        )


def _row_count(conn):
    return len(list_sessions(conn, include_lineage=True))




@pytest.mark.parametrize("source", PROCESS_BOOT_SOURCES)
def test_a_process_boot_source_is_a_sibling(source):
    assert classify_uuid_divergence(source) == DIVERGENCE_SIBLING_PROCESS
    assert mints_a_row(classify_uuid_divergence(source)) is False


@pytest.mark.parametrize("source", IN_PROCESS_TRANSITION_SOURCES)
def test_an_in_process_transition_is_still_a_fork(source):
    assert classify_uuid_divergence(source) == DIVERGENCE_IN_PROCESS_FORK
    assert mints_a_row(classify_uuid_divergence(source)) is True


@pytest.mark.parametrize("source", [None, "", "teleport_from_the_future", 7])
def test_an_unrecognised_source_is_a_could_not_evaluate(source):
    assert classify_uuid_divergence(source) == DIVERGENCE_SOURCE_UNRECOGNISED
    assert mints_a_row(classify_uuid_divergence(source)) is True


def test_an_unknown_verdict_never_authorises_a_write():
    assert mints_a_row("something_nobody_defined") is False




def test_the_panes_own_first_sessionstart_still_binds(conn):
    with transaction(conn):
        record_instance(
            conn,
            socket=SOCKET,
            name=NAME,
            epoch=EPOCH,
            origin=SESSION_ORIGIN_ADOPTED,
            working_dir="/tmp/proj",
        )

    result = _record(conn, PANE_UUID, "startup")

    assert result.outcome == LINEAGE_BOUND
    row = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert row["claude_session_uuid"] == PANE_UUID
    assert _row_count(conn) == 1




def test_a_sibling_startup_does_not_insert_a_row(conn, pane):
    before = _row_count(conn)

    result = _record(conn, SIBLING_UUID, "startup")

    assert result.outcome == LINEAGE_SIBLING
    assert result.wrote is False
    assert LINEAGE_SIBLING in LINEAGE_NO_WRITE
    assert _row_count(conn) == before, "a sibling session minted a row"

    row = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert row["claude_session_uuid"] == PANE_UUID

    stored = {
        r["claude_session_uuid"] for r in list_sessions(conn, include_lineage=True)
    }
    assert SIBLING_UUID not in stored


def test_a_sibling_resume_does_not_insert_a_row(conn, pane):
    before = _row_count(conn)

    result = _record(conn, "5fa9eb3b-9d82-4853-8d03-1c191a75fe65", "resume")

    assert result.outcome == LINEAGE_SIBLING
    assert _row_count(conn) == before


def test_a_sibling_title_never_lands_on_the_panes_row(conn, pane):
    _record(conn, PANE_UUID, "startup", title="the pane's own name")
    _record(conn, SIBLING_UUID, "startup", title="a stranger's name")

    row = get_instance(conn, socket=SOCKET, name=NAME, epoch=EPOCH)
    assert row["claude_title"] == "the pane's own name"




def test_the_same_sibling_event_twice_still_inserts_nothing(conn, pane):
    before = _row_count(conn)

    first = _record(conn, SIBLING_UUID, "startup")
    second = _record(conn, SIBLING_UUID, "startup")

    assert first.outcome == LINEAGE_SIBLING
    assert second.outcome == LINEAGE_SIBLING
    assert _row_count(conn) == before


def test_a_real_fork_arriving_after_a_sibling_still_mints(conn, pane):
    _record(conn, SIBLING_UUID, "startup")
    before = _row_count(conn)

    forked = _record(conn, "aaaaaaaa-0000-4000-8000-00000000000f", "clear")

    assert forked.outcome == LINEAGE_FORKED
    assert forked.parent_row_id == pane
    assert _row_count(conn) == before + 1


def test_a_sibling_uuid_we_already_stored_is_still_continued(conn, pane):
    result = _record(conn, PANE_UUID, "resume")
    assert result.outcome == LINEAGE_CONTINUED
    assert _row_count(conn) == 1
