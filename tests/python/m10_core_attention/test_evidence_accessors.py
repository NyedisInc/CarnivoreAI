from __future__ import annotations

from types import SimpleNamespace

from src.core.attention.evidence import Evidence


def _bound(**fields):
    row = SimpleNamespace(**fields)
    for name in ("active_pane", "active_transcript"):
        setattr(row, name, getattr(Evidence, name).__get__(row))
    return row


def _claude(pane=None, newest=None):
    return _bound(codex=None, pane=pane, transcript=SimpleNamespace(newest_append_at=newest))


def _codex(pane=None, last=None):
    return _bound(codex=SimpleNamespace(pane=pane, transcript=SimpleNamespace(last_append_at=last)),
                  pane="claude-pane", transcript="claude-facts")


def test_claude_row_reads_its_own_fields() -> None:
    row = _claude(pane=SimpleNamespace(shows_no_dialog=True), newest="t")
    assert Evidence.active_pane(row) is row.pane
    assert Evidence.append_at(row) == "t"
    assert Evidence.dialog_clear(row) is True


def test_codex_row_reads_the_codex_fields_and_clear_needs_a_positive_false() -> None:
    assert Evidence.append_at(_codex(last="c")) == "c"
    assert Evidence.dialog_clear(_codex(pane=SimpleNamespace(approval_dialog=False))) is True
    assert Evidence.dialog_clear(_codex(pane=SimpleNamespace(approval_dialog=None))) is False
    assert Evidence.dialog_clear(_codex(pane=None)) is False
    assert Evidence.dialog_clear(_claude(pane=None)) is False
