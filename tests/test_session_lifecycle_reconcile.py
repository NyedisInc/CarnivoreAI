
from __future__ import annotations

import sys
from contextlib import closing
from pathlib import Path

import pytest

from tests.lifecycle_helpers import (
    ENTRY_FUNCTION,
    MODULE_PATH,
    ROOT,
    SOCKET,
    WRITER_FUNCTION,
    CountingConnection,
    ExplodingConnection,
    add_row,
    conn,
    function_named,
    live,
    module_ast,
    row_by_uuid,
    sql_literals,
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402,F401

import sqlite3

from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_SOURCE_IMPORT,
    SESSION_LIFECYCLE_SOURCE_PROBE_FAILED,
    SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
    SESSION_LIFECYCLE_STOPPED,
    SESSION_LIFECYCLE_UNKNOWN,
    SESSION_ORIGIN_ADOPTED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_lifecycle import (
    RECONCILE_EVALUATED,
    RECONCILE_LISTING_INCOMPLETE,
    RECONCILE_NO_TABLE,
    RECONCILE_PROBE_UNAVAILABLE,
    live_instance_keys,
    reconcile_from_listing,
)
from src.core.session_store import list_sessions
from src.core.tmux_listing import (
    REASON_NO_SERVER,
    REASON_PROBE_ERROR,
    REASON_TIMEOUT,
    REASON_TMUX_MISSING,
    TmuxListing,
)
from src.core.tmux_stderr import REASON_CONNECT_FAILED




def test_row_present_in_an_ok_listing_stays_running(conn):
    add_row(conn, uuid="u-live", name="cloude_a", epoch=1000)
    with transaction(conn):
        outcome = reconcile_from_listing(
            conn, listing=live(("cloude_a", 1000)), socket=SOCKET
        )
    assert outcome.evaluated is True
    assert outcome.outcome == RECONCILE_EVALUATED
    assert outcome.stopped_uuids == ()
    assert outcome.examined == 1
    row = row_by_uuid(conn, "u-live")
    assert row["lifecycle"] == SESSION_LIFECYCLE_RUNNING
    assert row["lifecycle_source"] == SESSION_LIFECYCLE_SOURCE_IMPORT


def test_row_absent_from_an_ok_listing_becomes_stopped_with_tmux_missing(conn):
    add_row(conn, uuid="u-dead", name="cloude_gone", epoch=900)
    add_row(conn, uuid="u-live", name="cloude_a", epoch=1000)
    with transaction(conn):
        outcome = reconcile_from_listing(
            conn,
            listing=live(("cloude_a", 1000)),
            socket=SOCKET,
            now="2026-08-18T12:00:00.000000Z",
        )
    assert outcome.evaluated is True
    assert outcome.stopped_uuids == ("u-dead",)
    assert outcome.changed is True

    dead = row_by_uuid(conn, "u-dead")
    assert dead["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert dead["lifecycle_source"] == SESSION_LIFECYCLE_SOURCE_TMUX_MISSING
    assert dead["lifecycle_checked_at"] == "2026-08-18T12:00:00.000000Z"
    assert dead["last_seen_running_at"] == "2026-08-18T00:00:00.000000Z"

    assert row_by_uuid(conn, "u-live")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_a_reaped_row_reaches_the_recent_group(conn):
    add_row(conn, uuid="u-dead", name="cloude_gone", epoch=900)
    recent = list_sessions(
        conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
    )
    assert recent == [], "arrangement: RECENT must start empty"

    with transaction(conn):
        reconcile_from_listing(conn, listing=live(), socket=SOCKET)

    recent = list_sessions(
        conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
    )
    assert [r["session_uuid"] for r in recent] == ["u-dead"]


def test_an_empty_but_successful_listing_reaps_everything(conn):
    add_row(conn, uuid="u-a", name="cloude_a", epoch=1000)
    add_row(conn, uuid="u-b", name="cloude_b", epoch=1001)
    listing = TmuxListing.answered([], reason=REASON_NO_SERVER)
    assert listing.ok is True
    with transaction(conn):
        outcome = reconcile_from_listing(conn, listing=listing, socket=SOCKET)
    assert set(outcome.stopped_uuids) == {"u-a", "u-b"}




@pytest.mark.parametrize(
    "reason",
    [REASON_TIMEOUT, REASON_TMUX_MISSING, REASON_PROBE_ERROR,
     REASON_CONNECT_FAILED, "exit_2"],
)
def test_row_absent_from_a_failed_listing_does_not_change(conn, reason):
    add_row(conn, uuid="u-a", name="cloude_a", epoch=1000)
    before = row_by_uuid(conn, "u-a")

    listing = TmuxListing.unavailable(reason, detail="probe said nothing")
    assert listing.sessions == [], "arrangement: an unavailable listing has no rows"

    with transaction(conn):
        outcome = reconcile_from_listing(conn, listing=listing, socket=SOCKET)

    assert outcome.evaluated is False
    assert outcome.outcome == RECONCILE_PROBE_UNAVAILABLE
    assert outcome.stopped_uuids == ()
    assert outcome.changed is False
    assert outcome.reason == reason
    assert row_by_uuid(conn, "u-a") == before


@pytest.mark.parametrize(
    "reason", [REASON_TIMEOUT, REASON_TMUX_MISSING, REASON_PROBE_ERROR]
)
def test_a_failed_listing_never_touches_the_connection_at_all(reason):
    outcome = reconcile_from_listing(
        ExplodingConnection(),
        listing=TmuxListing.unavailable(reason),
        socket=SOCKET,
    )
    assert outcome.evaluated is False
    assert outcome.outcome == RECONCILE_PROBE_UNAVAILABLE


def test_a_failed_listing_issues_zero_statements(conn):
    add_row(conn, uuid="u-a", name="cloude_a", epoch=1000)
    spy = CountingConnection(conn)
    outcome = reconcile_from_listing(
        spy, listing=TmuxListing.unavailable(REASON_TIMEOUT), socket=SOCKET
    )
    assert outcome.evaluated is False
    assert spy.statements == []


def test_probe_failed_source_is_never_written(conn):
    add_row(conn, uuid="u-a", name="cloude_a", epoch=1000)
    for listing in (
        TmuxListing.unavailable(REASON_TIMEOUT),
        TmuxListing.answered([], refused_rows=1),
        live(("cloude_a", 1000)),
        live(),
    ):
        with transaction(conn):
            reconcile_from_listing(conn, listing=listing, socket=SOCKET)
    sources = {
        r["lifecycle_source"] for r in list_sessions(conn)
    }
    assert SESSION_LIFECYCLE_SOURCE_PROBE_FAILED not in sources
    source_text = MODULE_PATH.read_text(encoding="utf-8")
    assert "SESSION_LIFECYCLE_SOURCE_PROBE_FAILED" not in source_text.split(
        '"""', 2
    )[2], "probe_failed must not appear in the module's CODE, only its prose"


def test_an_incomplete_but_ok_listing_does_not_reap(conn):
    add_row(conn, uuid="u-a", name="cloude_a", epoch=1000)
    listing = TmuxListing.answered(
        [{"name": "cloude_b", "created_at_epoch": 2000}], refused_rows=1
    )
    assert listing.ok is True
    assert listing.complete is False
    with transaction(conn):
        outcome = reconcile_from_listing(conn, listing=listing, socket=SOCKET)
    assert outcome.evaluated is False
    assert outcome.outcome == RECONCILE_LISTING_INCOMPLETE
    assert row_by_uuid(conn, "u-a")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


@pytest.mark.parametrize(
    "row",
    [
        {"name": "cloude_x"},
        {"created_at_epoch": 1},
        {"name": "", "created_at_epoch": 1},
        {"name": "cloude_x", "created_at_epoch": None},
        {"name": "cloude_x", "created_at_epoch": "1000"},
        {"name": "cloude_x", "created_at_epoch": True},
        "cloude_x",
    ],
)
def test_a_listing_row_with_no_readable_identity_does_not_reap(conn, row):
    add_row(conn, uuid="u-a", name="cloude_a", epoch=1000)
    with transaction(conn):
        outcome = reconcile_from_listing(
            conn, listing=TmuxListing.answered([row]), socket=SOCKET
        )
    assert outcome.evaluated is False
    assert outcome.outcome == RECONCILE_LISTING_INCOMPLETE
    assert row_by_uuid(conn, "u-a")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_live_instance_keys_reads_a_clean_listing(conn):
    assert live_instance_keys(
        [{"name": "a", "created_at_epoch": 7}, {"name": "b", "created_at_epoch": 8}]
    ) == {("a", 7), ("b", 8)}
    assert live_instance_keys([]) == set()




def test_a_reused_name_with_a_different_epoch_does_not_reap_the_live_row(conn):
    add_row(
        conn,
        uuid="u-old",
        name="cloude_a",
        epoch=1000,
        origin=SESSION_ORIGIN_ADOPTED,
        adopted_at="2026-08-01T00:00:00.000000Z",
        tmux_session_id="$1",
    )
    add_row(conn, uuid="u-new", name="cloude_a", epoch=2000, tmux_session_id="$2")

    with transaction(conn):
        outcome = reconcile_from_listing(
            conn, listing=live(("cloude_a", 2000)), socket=SOCKET
        )

    assert outcome.stopped_uuids == ("u-old",)
    new = row_by_uuid(conn, "u-new")
    assert new["lifecycle"] == SESSION_LIFECYCLE_RUNNING

    old = row_by_uuid(conn, "u-old")
    assert old["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert old["origin"] == SESSION_ORIGIN_ADOPTED
    assert old["adopted_at"] == "2026-08-01T00:00:00.000000Z"
    assert old["session_uuid"] == "u-old"
    assert old["tmux_session_id"] == "$1"


def test_a_row_with_no_instance_triple_is_never_reaped(conn):
    add_row(conn, uuid="u-noname", name=None, epoch=None)
    add_row(conn, uuid="u-noepoch", name="cloude_a", epoch=None)
    with transaction(conn):
        outcome = reconcile_from_listing(conn, listing=live(), socket=SOCKET)
    assert outcome.stopped_uuids == ()
    assert row_by_uuid(conn, "u-noname")["lifecycle"] == SESSION_LIFECYCLE_RUNNING
    assert row_by_uuid(conn, "u-noepoch")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_rows_on_another_socket_are_never_reaped(conn):
    add_row(conn, uuid="u-other", name="other_a", epoch=1000, socket="somewhere_else")
    with transaction(conn):
        outcome = reconcile_from_listing(conn, listing=live(), socket=SOCKET)
    assert outcome.stopped_uuids == ()
    assert outcome.examined == 0
    assert row_by_uuid(conn, "u-other")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_an_unknown_row_is_not_promoted_to_stopped(conn):
    add_row(
        conn, uuid="u-unknown", name="cloude_u", epoch=1, lifecycle=SESSION_LIFECYCLE_UNKNOWN
    )
    with transaction(conn):
        outcome = reconcile_from_listing(conn, listing=live(), socket=SOCKET)
    assert outcome.stopped_uuids == ()
    assert row_by_uuid(conn, "u-unknown")["lifecycle"] == SESSION_LIFECYCLE_UNKNOWN




def test_reconciling_twice_with_no_change_writes_nothing(conn):
    add_row(conn, uuid="u-dead", name="cloude_gone", epoch=900)
    add_row(conn, uuid="u-live", name="cloude_a", epoch=1000)
    listing = live(("cloude_a", 1000))

    with transaction(conn):
        first = reconcile_from_listing(conn, listing=listing, socket=SOCKET)
    assert first.stopped_uuids == ("u-dead",)

    spy = CountingConnection(conn)
    second = reconcile_from_listing(spy, listing=listing, socket=SOCKET)
    assert second.evaluated is True
    assert second.stopped_uuids == ()
    assert second.changed is False
    assert spy.writes == [], f"a no-op reconcile wrote: {spy.writes}"


def test_a_steady_state_reconcile_writes_nothing_at_all(conn):
    add_row(conn, uuid="u-live", name="cloude_a", epoch=1000)
    spy = CountingConnection(conn)
    outcome = reconcile_from_listing(
        spy, listing=live(("cloude_a", 1000)), socket=SOCKET
    )
    assert outcome.evaluated is True
    assert spy.writes == []


def test_an_archived_row_is_not_resurrected(conn):
    add_row(
        conn,
        uuid="u-arch",
        name="cloude_arch",
        epoch=500,
        archived_at="2026-08-10T00:00:00.000000Z",
    )
    with transaction(conn):
        outcome = reconcile_from_listing(conn, listing=live(), socket=SOCKET)

    row = row_by_uuid(conn, "u-arch")
    assert outcome.stopped_uuids == ("u-arch",)
    assert row["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert row["archived_at"] == "2026-08-10T00:00:00.000000Z"
    recent = list_sessions(
        conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
    )
    assert [r["session_uuid"] for r in recent] == []


def test_a_pre_v2_database_is_a_real_answer_of_nothing_to_do(tmp_path):
    path = tmp_path / "empty.db"
    with closing(sqlite3.connect(path)) as raw:
        outcome = reconcile_from_listing(raw, listing=live(), socket=SOCKET)
    assert outcome.evaluated is False
    assert outcome.outcome == RECONCILE_NO_TABLE


