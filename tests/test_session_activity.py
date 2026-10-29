
from __future__ import annotations

from datetime import datetime


from src.core.session_activity import (
    WORKING_HEARTBEAT_TIMEOUT_SECONDS,
    map_tmux_fallback,
)
from src.core.session_status import (
    ALL_ACTIVITY_STATUSES,
    STATUS_DEAD,
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
)

T0 = datetime(2026, 9, 8, 12, 0, 0)




def test_a_running_pane_is_unknown_and_never_working():
    assert map_tmux_fallback(STATUS_RUNNING) == STATUS_UNKNOWN
    assert map_tmux_fallback(STATUS_RUNNING, unread=True) == STATUS_UNKNOWN


def test_a_dead_pane_reads_dead():
    assert map_tmux_fallback(STATUS_DEAD) == STATUS_DEAD
    assert map_tmux_fallback(STATUS_DEAD, unread=True) == STATUS_DEAD


def test_an_idle_pane_splits_on_the_unread_flag():
    assert map_tmux_fallback(STATUS_IDLE) == STATUS_IDLE
    assert map_tmux_fallback(STATUS_IDLE, unread=True) == STATUS_FINISHED_UNREAD


def test_an_unknown_pane_stays_unknown_even_when_unread():
    assert map_tmux_fallback(STATUS_UNKNOWN) == STATUS_UNKNOWN
    assert map_tmux_fallback(STATUS_UNKNOWN, unread=True) == STATUS_UNKNOWN


def test_the_fallback_never_answers_outside_the_declared_vocabulary():
    for raw in (STATUS_RUNNING, STATUS_IDLE, STATUS_DEAD, STATUS_UNKNOWN, "garbage"):
        for unread in (True, False):
            assert map_tmux_fallback(raw, unread=unread) in ALL_ACTIVITY_STATUSES


def test_an_unrecognised_tmux_status_is_unknown_and_does_not_raise():
    assert map_tmux_fallback("something_new") == STATUS_UNKNOWN




def test_the_heartbeat_window_is_the_one_every_importer_reads():
    from src.core.activity_persist import (
        WORKING_HEARTBEAT_TIMEOUT_SECONDS as PERSIST,
    )
    from src.core.session_transcript_status import (
        WORKING_HEARTBEAT_TIMEOUT_SECONDS as TRANSCRIPT,
    )

    assert PERSIST is WORKING_HEARTBEAT_TIMEOUT_SECONDS
    assert TRANSCRIPT is WORKING_HEARTBEAT_TIMEOUT_SECONDS


def test_the_heartbeat_window_is_a_positive_number_of_seconds():
    assert isinstance(WORKING_HEARTBEAT_TIMEOUT_SECONDS, int)
    assert WORKING_HEARTBEAT_TIMEOUT_SECONDS > 0
