from __future__ import annotations

import pytest

from src.core import restart_live_gate
from src.core.session_ops import row_probe
from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT, TMUX_UNKNOWN, TmuxPresence

NAME = "carnivore_probe_demo"


def _measure(monkeypatch: pytest.MonkeyPatch, line, *, row_epoch, strict: bool) -> TmuxPresence:
    monkeypatch.setattr(row_probe, "measure_presence", lambda name, socket: TmuxPresence(TMUX_PRESENT, "x"))
    monkeypatch.setattr(restart_live_gate, "probe_line", lambda name, socket: line)
    return row_probe.measure_row_presence({"tmux_created_epoch": row_epoch}, NAME, "s", require_known_epoch=strict)


def test_own_pane_is_present_and_carries_its_session_id(monkeypatch) -> None:
    got = _measure(monkeypatch, f"0|17|{NAME}|$4", row_epoch=17, strict=True)
    assert (got.outcome, got.session_id) == (TMUX_PRESENT, "$4")


def test_an_unknown_observed_epoch_is_unknown_with_the_flag_and_present_without(monkeypatch) -> None:
    assert _measure(monkeypatch, None, row_epoch=17, strict=True).outcome == TMUX_UNKNOWN
    assert _measure(monkeypatch, None, row_epoch=17, strict=False).outcome == TMUX_PRESENT


def test_a_line_with_no_session_id_is_unproven_with_the_flag(monkeypatch) -> None:
    assert _measure(monkeypatch, f"0|17|{NAME}", row_epoch=17, strict=True).outcome == TMUX_UNKNOWN
    assert _measure(monkeypatch, f"0|17|{NAME}", row_epoch=17, strict=False).outcome == TMUX_PRESENT


def test_an_unrecorded_row_epoch_is_a_guard_unknown_with_the_flag(monkeypatch) -> None:
    assert _measure(monkeypatch, f"0|17|{NAME}|$4", row_epoch=None, strict=True).outcome == TMUX_UNKNOWN
    assert _measure(monkeypatch, f"0|17|{NAME}|$4", row_epoch=None, strict=False).outcome == TMUX_PRESENT


@pytest.mark.parametrize("strict", [True, False])
def test_a_different_known_epoch_is_gone_and_flagged_other_instance(monkeypatch, strict: bool) -> None:
    got = _measure(monkeypatch, f"0|99|{NAME}|$4", row_epoch=17, strict=strict)
    assert (got.outcome, got.other_instance, got.session_id) == (TMUX_GONE, True, None)


@pytest.mark.parametrize("line, sid", [("0|17|a|b|$0", "$0"), ("0|17|a|b", None), ("1|17|x|$12|y|$3", "$3"), ("1|17|x|$12|y", None)])
def test_a_name_with_a_pipe_parses_whole_with_or_without_an_id(line: str, sid) -> None:
    parsed = restart_live_gate.parse_probe(line)
    assert parsed is not None and parsed[3] == sid
    assert parsed[2] == line.split("|", 2)[2].rpartition("|")[0] if sid else parsed[2] == line.split("|", 2)[2]
    assert restart_live_gate.probe_epoch(line, parsed[2]) == 17
