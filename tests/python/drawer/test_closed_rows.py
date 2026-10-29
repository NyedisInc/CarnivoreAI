
from __future__ import annotations

import pytest

from src.api.session_listing_collections import running_join_row
from src.core.session_sleep import is_closed

STOPPED = "stopped"


def row(**kw):
    base = {"lifecycle": STOPPED, "lifecycle_source": "closed_by_user", "tmux_created_epoch": 5,
            "archived_at": None, "tmux_name": "carnivore_x", "claude_session_uuid": None}
    base.update(kw)
    return base


@pytest.mark.parametrize("kw, expected", [
    ({}, True),
    ({"lifecycle_source": "tmux_missing"}, True),
    ({"lifecycle_source": "slept_by_user"}, False),
    ({"lifecycle_source": "slept_by_timer"}, False),
    ({"lifecycle_source": "pane_dead", "claude_session_uuid": "c1"}, False),
    ({"lifecycle_source": "pane_dead"}, True),
    ({"archived_at": "2026-10-01T00:00:00"}, False),
    ({"tmux_created_epoch": None}, False),
    ({"lifecycle": "running"}, False),
])
def test_is_closed(kw, expected):
    assert is_closed(row(**kw)) is expected


def test_is_closed_tolerates_no_row():
    assert is_closed(None) is False and is_closed({}) is False


def test_pushed_records_carry_closed_rows_but_not_other_history():
    assert running_join_row(row(), set()) is True
    assert running_join_row(row(tmux_created_epoch=None, lifecycle_source="import"), set()) is False
    assert running_join_row(row(archived_at="2026-10-01T00:00:00"), set()) is False
