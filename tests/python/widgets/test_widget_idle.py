
from __future__ import annotations

from scripts.widgets.idle import idle_of

CLEAN_WIDGET = "core.notes"


def test_a_clean_widget_sends_nothing_hidden(page_and_base) -> None:
    page, base = page_and_base
    got = idle_of(page, base, CLEAN_WIDGET)
    assert got["hidden"]["requests"] == 0, got["hiddenRoutes"]
    assert got["shown"]["requests"] == 0, got["shownRoutes"]
    assert got["failures"] == []


def test_a_planted_hidden_poll_reads_twelve_or_thirteen_and_fails(page_and_base) -> None:
    page, base = page_and_base
    got = idle_of(page, base, CLEAN_WIDGET, plant=True)
    assert got["hidden"]["requests"] in (12, 13), got
    assert got["hiddenRoutes"] == {"GET /planted-offender": got["hidden"]["requests"]}
    assert len(got["failures"]) == 1
