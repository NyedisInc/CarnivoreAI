
from __future__ import annotations

import sys

import pytest

from tests.lifecycle_helpers import (
    ROOT,
    SOCKET,
    CountingConnection,
    add_row,
    conn,
    live,
    row_by_uuid,
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402,F401

from src.core.db import transaction
from src.core.db_models import (
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_SOURCE_TMUX_MISSING,
    SESSION_LIFECYCLE_STOPPED,
)
from src.core.session_lifecycle import reconcile_from_listing
from src.core.session_pane_death import (
    LIFECYCLE_SOURCE_PANE_DEAD,
    PaneDeath,
    pane_death,
)
from src.core.session_respawn import PANE_ALIVE, PANE_DEAD, PANE_UNKNOWN
from src.core.session_status_map import StatusMap, status_map_from_listing
from src.core.session_store import list_sessions
from src.core.tmux_listing import TmuxListing

OTHER_SOCKET = "cloude_pytest_somewhere_else"


def panes(*rows, complete=True, socket=SOCKET):
    return StatusMap(
        {
            name: {
                "name": name,
                "created_at_epoch": epoch,
                "pane_dead": dead,
                "pane_current_command": "sh",
            }
            for name, epoch, dead in rows
        },
        complete=complete,
        socket=socket,
    )




def test_a_measured_dead_pane_on_this_socket_and_this_instance_reads_dead():
    verdict = pane_death(
        panes(("cloude_a", 1000, "1")),
        "cloude_a",
        1000,
        backend_socket=SOCKET,
    )
    assert verdict.outcome == PANE_DEAD
    assert verdict.dead is True
    assert verdict.pane_dead_raw == "1"


def test_a_measured_live_pane_reads_alive_and_is_not_dead():
    verdict = pane_death(
        panes(("cloude_a", 1000, "0")),
        "cloude_a",
        1000,
        backend_socket=SOCKET,
    )
    assert verdict.outcome == PANE_ALIVE
    assert verdict.dead is False




def test_no_pane_listing_at_all_is_unknown():
    assert pane_death(None, "cloude_a", 1000, backend_socket=SOCKET).outcome == (
        PANE_UNKNOWN
    )


def test_an_incomplete_listing_never_reads_dead_even_carrying_a_dead_row():
    incomplete = panes(("cloude_a", 1000, "1"), complete=False)
    assert incomplete.get("cloude_a")["pane_dead"] == "1", "arrangement"
    verdict = pane_death(incomplete, "cloude_a", 1000, backend_socket=SOCKET)
    assert verdict.outcome == PANE_UNKNOWN
    assert verdict.dead is False


def test_a_plain_dict_states_neither_completeness_nor_socket_and_is_refused():
    raw = {
        "cloude_a": {
            "name": "cloude_a",
            "created_at_epoch": 1000,
            "pane_dead": "1",
        }
    }
    assert pane_death(raw, "cloude_a", 1000, backend_socket=SOCKET).outcome == (
        PANE_UNKNOWN
    )


@pytest.mark.parametrize(
    "listing_socket,backend_socket",
    [
        (OTHER_SOCKET, SOCKET),
        (SOCKET, OTHER_SOCKET),
        (None, SOCKET),
        (SOCKET, None),
        (None, None),
    ],
)
def test_a_listing_from_another_socket_or_an_unstated_one_is_unknown(
    listing_socket, backend_socket
):
    verdict = pane_death(
        panes(("cloude_a", 1000, "1"), socket=listing_socket),
        "cloude_a",
        1000,
        backend_socket=backend_socket,
    )
    assert verdict.outcome == PANE_UNKNOWN


def test_a_name_the_listing_does_not_carry_is_unknown_never_dead():
    verdict = pane_death(
        panes(("cloude_b", 1000, "1")),
        "cloude_a",
        1000,
        backend_socket=SOCKET,
    )
    assert verdict.outcome == PANE_UNKNOWN


def test_a_row_for_a_different_instance_of_the_same_name_is_unknown():
    verdict = pane_death(
        panes(("cloude_a", 1000, "1")),
        "cloude_a",
        2000,
        backend_socket=SOCKET,
    )
    assert verdict.outcome == PANE_UNKNOWN


@pytest.mark.parametrize("row_epoch", [None, "1000", True, 1.0])
def test_a_row_with_no_readable_epoch_is_unknown(row_epoch):
    verdict = pane_death(
        panes(("cloude_a", row_epoch, "1")),
        "cloude_a",
        1000,
        backend_socket=SOCKET,
    )
    assert verdict.outcome == PANE_UNKNOWN


@pytest.mark.parametrize("stored_epoch", [None, "1000", True])
def test_a_stored_row_with_no_readable_epoch_is_unknown(stored_epoch):
    verdict = pane_death(
        panes(("cloude_a", 1000, "1")),
        "cloude_a",
        stored_epoch,
        backend_socket=SOCKET,
    )
    assert verdict.outcome == PANE_UNKNOWN


@pytest.mark.parametrize("raw", [None, "", "  ", "yes", "true", "2", "-", 1, True])
def test_an_unreadable_pane_dead_field_is_unknown_and_never_dead(raw):
    verdict = pane_death(
        panes(("cloude_a", 1000, raw)),
        "cloude_a",
        1000,
        backend_socket=SOCKET,
    )
    assert verdict.outcome == PANE_UNKNOWN
    assert verdict.dead is False


def test_a_stored_row_with_no_tmux_name_is_unknown():
    assert pane_death(
        panes(("cloude_a", 1000, "1")), None, 1000, backend_socket=SOCKET
    ).outcome == PANE_UNKNOWN


def test_a_listing_row_that_is_not_a_mapping_is_unknown():
    bad = StatusMap({"cloude_a": "dead"}, complete=True, socket=SOCKET)
    assert pane_death(
        bad, "cloude_a", 1000, backend_socket=SOCKET
    ).outcome == PANE_UNKNOWN


def test_only_pane_dead_is_ever_true_for_the_dead_property():
    assert PaneDeath(PANE_DEAD).dead is True
    assert PaneDeath(PANE_ALIVE).dead is False
    assert PaneDeath(PANE_UNKNOWN).dead is False




def test_a_listed_session_with_a_dead_pane_is_reaped_and_says_why(conn):
    add_row(conn, uuid="u-husk", name="cloude_husk", epoch=900)
    add_row(conn, uuid="u-live", name="cloude_a", epoch=1000)
    with transaction(conn):
        outcome = reconcile_from_listing(
            conn,
            listing=live(("cloude_husk", 900), ("cloude_a", 1000)),
            socket=SOCKET,
            pane_status=panes(("cloude_husk", 900, "1"), ("cloude_a", 1000, "0")),
            now="2026-09-10T12:00:00.000000Z",
        )
    assert outcome.evaluated is True
    assert outcome.stopped_uuids == ("u-husk",)
    assert outcome.pane_dead_stopped == 1

    husk = row_by_uuid(conn, "u-husk")
    assert husk["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert husk["lifecycle_source"] == LIFECYCLE_SOURCE_PANE_DEAD
    assert husk["lifecycle_checked_at"] == "2026-09-10T12:00:00.000000Z"
    assert husk["last_seen_running_at"] == "2026-08-18T00:00:00.000000Z"
    assert husk["archived_at"] is None
    assert husk["session_uuid"] == "u-husk"

    assert row_by_uuid(conn, "u-live")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_a_pane_dead_reap_reaches_the_recent_group(conn):
    add_row(conn, uuid="u-husk", name="cloude_husk", epoch=900)
    assert (
        list_sessions(
            conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
        )
        == []
    ), "arrangement: RECENT must start empty"

    with transaction(conn):
        reconcile_from_listing(
            conn,
            listing=live(("cloude_husk", 900)),
            socket=SOCKET,
            pane_status=panes(("cloude_husk", 900, "1")),
        )

    recent = list_sessions(
        conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
    )
    assert [r["session_uuid"] for r in recent] == ["u-husk"]


def _refuse(conn, **kwargs):
    counting = CountingConnection(conn)
    reconcile_from_listing(
        counting,
        listing=live(("cloude_a", 1000)),
        socket=SOCKET,
        **kwargs,
    )
    return counting.writes


@pytest.mark.parametrize(
    "pane_status,why",
    [
        (None, "no pane listing was taken"),
        (panes(("cloude_a", 1000, "0"), complete=False), "listing incomplete"),
        (panes(("cloude_a", 1000, "1"), complete=False), "incomplete AND dead"),
        (panes(("cloude_a", 1000, "0")), "measured alive"),
        (panes(("cloude_a", 1000, "")), "pane_dead unreadable"),
        (panes(("cloude_a", 1000, None)), "pane_dead absent"),
        (panes(("cloude_a", 1000, "1"), socket=OTHER_SOCKET), "wrong socket"),
        (panes(("cloude_a", 1000, "1"), socket=None), "socket unstated"),
        (panes(("cloude_b", 1000, "1")), "a different session is dead"),
        (panes(("cloude_a", 2000, "1")), "a different instance of this name"),
        (panes(("cloude_a", None, "1")), "the row cannot be identified"),
    ],
)
def test_a_live_listed_row_is_never_reaped_on_anything_but_a_measurement(
    conn, pane_status, why
):
    add_row(conn, uuid="u-a", name="cloude_a", epoch=1000)
    with transaction(conn):
        writes = _refuse(conn, pane_status=pane_status)
    assert writes == [], f"a row was written on: {why}"
    assert row_by_uuid(conn, "u-a")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_a_failed_listing_never_reaps_even_with_a_dead_pane_in_hand(conn):
    add_row(conn, uuid="u-a", name="cloude_a", epoch=1000)
    with transaction(conn):
        outcome = reconcile_from_listing(
            conn,
            listing=TmuxListing.unavailable("timeout"),
            socket=SOCKET,
            pane_status=panes(("cloude_a", 1000, "1")),
        )
    assert outcome.evaluated is False
    assert outcome.stopped_uuids == ()
    assert row_by_uuid(conn, "u-a")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_rows_on_another_socket_are_still_never_reaped_by_the_dead_rung(conn):
    add_row(conn, uuid="u-other", name="cloude_a", epoch=1000, socket=OTHER_SOCKET)
    with transaction(conn):
        reconcile_from_listing(
            conn,
            listing=live(("cloude_a", 1000)),
            socket=SOCKET,
            pane_status=panes(("cloude_a", 1000, "1")),
        )
    assert row_by_uuid(conn, "u-other")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_reaping_the_same_husk_twice_writes_nothing_the_second_time(conn):
    add_row(conn, uuid="u-husk", name="cloude_husk", epoch=900)
    args = dict(
        listing=live(("cloude_husk", 900)),
        socket=SOCKET,
        pane_status=panes(("cloude_husk", 900, "1")),
    )
    with transaction(conn):
        first = reconcile_from_listing(conn, **args)
    assert first.stopped_uuids == ("u-husk",)

    counting = CountingConnection(conn)
    with transaction(conn):
        second = reconcile_from_listing(counting, **args)
    assert second.stopped_uuids == ()
    assert second.pane_dead_stopped == 0
    assert counting.writes == []




def test_the_absence_rung_still_reaps_with_no_pane_listing_supplied(conn):
    add_row(conn, uuid="u-gone", name="cloude_gone", epoch=900)
    add_row(conn, uuid="u-live", name="cloude_a", epoch=1000)
    with transaction(conn):
        outcome = reconcile_from_listing(
            conn, listing=live(("cloude_a", 1000)), socket=SOCKET
        )
    assert outcome.stopped_uuids == ("u-gone",)
    assert outcome.pane_dead_stopped == 0
    gone = row_by_uuid(conn, "u-gone")
    assert gone["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert gone["lifecycle_source"] == SESSION_LIFECYCLE_SOURCE_TMUX_MISSING


def test_the_two_rungs_coexist_and_keep_their_own_sources(conn):
    add_row(conn, uuid="u-gone", name="cloude_gone", epoch=900)
    add_row(conn, uuid="u-husk", name="cloude_husk", epoch=901)
    add_row(conn, uuid="u-live", name="cloude_a", epoch=1000)
    with transaction(conn):
        outcome = reconcile_from_listing(
            conn,
            listing=live(("cloude_husk", 901), ("cloude_a", 1000)),
            socket=SOCKET,
            pane_status=panes(("cloude_husk", 901, "1"), ("cloude_a", 1000, "0")),
        )
    assert set(outcome.stopped_uuids) == {"u-gone", "u-husk"}
    assert outcome.pane_dead_stopped == 1
    assert row_by_uuid(conn, "u-gone")["lifecycle_source"] == (
        SESSION_LIFECYCLE_SOURCE_TMUX_MISSING
    )
    assert row_by_uuid(conn, "u-husk")["lifecycle_source"] == (
        LIFECYCLE_SOURCE_PANE_DEAD
    )
    assert row_by_uuid(conn, "u-live")["lifecycle"] == SESSION_LIFECYCLE_RUNNING


def test_an_archived_row_with_a_dead_pane_stays_archived(conn):
    add_row(
        conn,
        uuid="u-arch",
        name="cloude_husk",
        epoch=900,
        archived_at="2026-08-01T00:00:00.000000Z",
    )
    with transaction(conn):
        reconcile_from_listing(
            conn,
            listing=live(("cloude_husk", 900)),
            socket=SOCKET,
            pane_status=panes(("cloude_husk", 900, "1")),
        )
    row = row_by_uuid(conn, "u-arch")
    assert row["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert row["archived_at"] == "2026-08-01T00:00:00.000000Z"
    assert (
        list_sessions(
            conn, lifecycle=SESSION_LIFECYCLE_STOPPED, include_archived=False
        )
        == []
    ), "an archived row must not surface in RECENT"




def test_the_builder_carries_completeness_and_socket_off_the_probe():
    listing = TmuxListing.answered(
        [{"name": "cloude_a", "pane_dead": "1", "created_at_epoch": 7}]
    )
    built = status_map_from_listing(listing, socket=SOCKET)
    assert built.complete is True
    assert built.socket == SOCKET
    assert pane_death(built, "cloude_a", 7, backend_socket=SOCKET).dead is True


def test_a_failed_pane_listing_builds_a_map_that_can_prove_nothing():
    built = status_map_from_listing(TmuxListing.unavailable("timeout"), socket=SOCKET)
    assert built.complete is False
    assert built.socket is None
    assert built == {}


def test_a_refused_row_makes_the_built_map_incomplete():
    listing = TmuxListing.answered(
        [{"name": "cloude_a", "pane_dead": "1", "created_at_epoch": 7}],
        refused_rows=1,
    )
    built = status_map_from_listing(listing, socket=SOCKET)
    assert built.complete is False
    assert pane_death(built, "cloude_a", 7, backend_socket=SOCKET).dead is False




def test_a_pane_dead_row_whose_same_instance_is_alive_again_returns_to_running(conn):
    add_row(conn, uuid="u-revived", name="cloude_a", epoch=1000)
    add_row(conn, uuid="u-gone", name="cloude_b", epoch=1000)
    add_row(conn, uuid="u-recycled", name="cloude_c", epoch=1000)
    with transaction(conn):
        reconcile_from_listing(
            conn,
            listing=live(("cloude_a", 1000), ("cloude_c", 1000)),
            socket=SOCKET,
            pane_status=panes(("cloude_a", 1000, "1"), ("cloude_c", 1000, "1")),
        )
    assert row_by_uuid(conn, "u-revived")["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert row_by_uuid(conn, "u-gone")["lifecycle_source"] == SESSION_LIFECYCLE_SOURCE_TMUX_MISSING

    with transaction(conn):
        reconcile_from_listing(
            conn,
            listing=live(("cloude_a", 1000), ("cloude_c", 2000)),
            socket=SOCKET,
            pane_status=panes(("cloude_a", 1000, "0"), ("cloude_c", 2000, "0")),
            now="2026-10-06T01:00:00.000000Z",
        )
    revived = row_by_uuid(conn, "u-revived")
    assert revived["lifecycle"] == SESSION_LIFECYCLE_RUNNING
    assert revived["lifecycle_source"] == "tmux_list"
    assert row_by_uuid(conn, "u-gone")["lifecycle"] == SESSION_LIFECYCLE_STOPPED
    assert row_by_uuid(conn, "u-recycled")["lifecycle"] == SESSION_LIFECYCLE_STOPPED
