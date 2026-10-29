from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.terminal_size import TerminalSizeNegotiator  # noqa: E402


def test_single_client_effective_size_equals_its_own_request():
    neg = TerminalSizeNegotiator()
    result = neg.set_client_size("sess-1", "client-a", 100, 40)

    assert result == (100, 40)
    assert neg.effective_size("sess-1") == (100, 40)
    assert neg.client_count("sess-1") == 1


def test_two_clients_effective_is_elementwise_minimum():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("sess-1", "client-a", 200, 50)
    result = neg.set_client_size("sess-1", "client-b", 90, 30)

    assert result == (90, 30)
    assert neg.effective_size("sess-1") == (90, 30)
    assert neg.client_count("sess-1") == 2


def test_small_client_disconnect_grows_effective_size_back():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("sess-1", "client-a", 200, 50)
    neg.set_client_size("sess-1", "client-b", 90, 30)
    assert neg.effective_size("sess-1") == (90, 30)

    result = neg.remove_client("sess-1", "client-b")

    assert result == (200, 50)
    assert neg.effective_size("sess-1") == (200, 50)
    assert neg.client_count("sess-1") == 1


def test_large_client_disconnect_effective_size_stays_small():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("sess-1", "client-a", 200, 50)
    neg.set_client_size("sess-1", "client-b", 90, 30)

    result = neg.remove_client("sess-1", "client-a")

    assert result is None
    assert neg.effective_size("sess-1") == (90, 30)
    assert neg.client_count("sess-1") == 1


def test_last_client_disconnect_leaves_no_clients_and_does_not_crash():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("sess-1", "client-a", 100, 40)

    result = neg.remove_client("sess-1", "client-a")

    assert result is None
    assert neg.effective_size("sess-1") is None
    assert neg.client_count("sess-1") == 0

    assert neg.remove_client("sess-1", "client-a") is None


def test_mixed_axes_take_minimum_per_axis_not_per_client():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("sess-1", "client-a", 80, 60)
    result = neg.set_client_size("sess-1", "client-b", 120, 20)

    assert result == (80, 20)
    assert neg.effective_size("sess-1") == (80, 20)


def test_non_positive_dimensions_are_ignored():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("sess-1", "client-a", 100, 40)

    result_zero = neg.set_client_size("sess-1", "client-a", 0, 40)
    result_negative = neg.set_client_size("sess-1", "client-a", 100, -5)

    assert result_zero is None
    assert result_negative is None
    assert neg.effective_size("sess-1") == (100, 40)
    assert neg.client_count("sess-1") == 1


def test_second_client_reporting_a_larger_size_does_not_change_effective():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("sess-1", "client-a", 80, 24)
    result = neg.set_client_size("sess-1", "client-b", 200, 60)

    assert result is None
    assert neg.effective_size("sess-1") == (80, 24)


def test_sessions_are_independent():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("sess-1", "client-a", 80, 24)
    neg.set_client_size("sess-2", "client-a", 200, 60)

    assert neg.effective_size("sess-1") == (80, 24)
    assert neg.effective_size("sess-2") == (200, 60)
    assert neg.client_count("sess-1") == 1
    assert neg.client_count("sess-2") == 1


def test_a_terminal_cell_votes_only_in_its_own_sessions_grid():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("ses_a", "primary-socket", 200, 60)
    changed = neg.set_client_size("ses_b", "cell-socket", 48, 14)

    assert changed == (48, 14), "the cell did not enter its own negotiation"
    assert neg.effective_size("ses_a") == (200, 60), "the cell re-gridded another session"
    assert neg.client_count("ses_a") == 1
    assert neg.client_count("ses_b") == 1

    neg.set_client_size("ses_b", "cell-socket", 30, 8)
    assert neg.effective_size("ses_b") == (30, 8)
    assert neg.effective_size("ses_a") == (200, 60)


def test_two_clients_on_ONE_session_is_the_case_that_must_not_happen():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("ses_a", "primary-socket", 200, 60)
    shrunk = neg.set_client_size("ses_a", "cell-socket", 48, 14)

    assert shrunk == (48, 14)
    assert neg.effective_size("ses_a") == (48, 14)
    assert neg.client_count("ses_a") == 2




def test_two_visible_clients_still_negotiate_smallest_wins():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("s", "a", 160, 47, voting=True)
    assert neg.set_client_size("s", "b", 82, 30, voting=True) == (82, 30)
    assert neg.effective_size("s") == (82, 30)


def test_a_hidden_client_is_left_out_of_the_minimum():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("s", "visible", 160, 47)
    assert neg.set_client_size("s", "hidden", 82, 30, voting=False) is None
    assert neg.effective_size("s") == (160, 47)
    assert neg.client_count("s") == 2


def test_hiding_the_constraining_client_grows_the_pane_back():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("s", "big", 160, 47)
    neg.set_client_size("s", "small", 82, 30)
    assert neg.set_client_size("s", "small", 82, 30, voting=False) == (160, 47)


def test_a_hidden_client_rejoins_by_voting_again():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("s", "big", 160, 47)
    neg.set_client_size("s", "small", 82, 30, voting=False)
    assert neg.set_client_size("s", "small", 90, 31) == (90, 31)


def test_when_every_client_is_hidden_the_last_size_is_kept():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("s", "a", 160, 47)
    neg.set_client_size("s", "b", 120, 40)
    assert neg.set_client_size("s", "b", 120, 40, voting=False) == (160, 47)
    assert neg.set_client_size("s", "a", 160, 47, voting=False) is None
    assert neg.effective_size("s") == (160, 47)
    assert neg.set_client_size("s", "a", 50, 10, voting=False) is None
    assert neg.effective_size("s") == (160, 47)


def test_a_departure_while_everyone_left_is_hidden_moves_nothing():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("s", "visible", 160, 47)
    neg.set_client_size("s", "hidden", 82, 30, voting=False)
    assert neg.remove_client("s", "visible") is None
    assert neg.effective_size("s") == (160, 47)


def test_a_client_arriving_hidden_on_an_empty_session_sizes_nothing():
    neg = TerminalSizeNegotiator()
    assert neg.set_client_size("s", "hidden", 82, 30, voting=False) is None
    assert neg.effective_size("s") is None


def test_an_old_client_that_never_says_hidden_still_votes():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("s", "new-visible", 160, 47)
    assert neg.set_client_size("s", "old", 82, 30) == (82, 30)


def test_a_withdrawn_client_that_leaves_is_forgotten_entirely():
    neg = TerminalSizeNegotiator()
    neg.set_client_size("s", "a", 160, 47)
    neg.set_client_size("s", "b", 82, 30, voting=False)
    neg.remove_client("s", "b")
    assert neg.set_client_size("s", "b", 82, 30) == (82, 30)
