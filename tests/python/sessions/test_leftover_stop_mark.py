from __future__ import annotations

from src.core import session_journal_store as store
from src.core.session_ops import close_intent
from tests.test_restore_offer_fold import LIVE, ROWS, _clocked, _m, _pane, _pass, _tick, task

A = LIVE[0]
KEY = ("local", "cloude", A["tmux_name"], A["tmux_created_epoch"])


def _unsettled_stop():
    with close_intent.stopping(*KEY):
        pass


def test_a_kill_landing_mid_measure_with_a_failed_write_is_not_offered_next_pass(tmp_path, monkeypatch):
    state = _clocked(tmp_path, monkeypatch, LIVE)
    all_live = _m([_pane(r) for r in LIVE])
    all_live.rows = ROWS

    def measure_while_the_kill_lands(*args, **kwargs):
        _unsettled_stop()
        return all_live

    monkeypatch.setattr(task, "measure", measure_while_the_kill_lands)
    state["now"] = "2026-09-24T07:02:00Z"
    assert not _pass(tmp_path).get("offer")
    assert KEY in close_intent._lingering, "measured live, mark left after the stamp: it must survive this pass"
    monkeypatch.setattr(task, "measure", lambda *a, **k: state["m"])
    assert not _tick(tmp_path, state, "2026-09-24T07:03:00Z", [LIVE[1], LIVE[2]], rows=ROWS).get("offer")
    assert KEY not in close_intent._lingering, "measured gone: recorded once, released"


def test_a_mark_from_a_stop_that_did_not_happen_is_dropped_when_a_later_pass_reads_the_pane_live(tmp_path, monkeypatch):
    state = _clocked(tmp_path, monkeypatch, LIVE)
    _unsettled_stop()
    state["now"] = "2026-09-24T07:02:00Z"
    assert not _pass(tmp_path).get("offer")
    assert KEY not in close_intent._lingering
    assert _tick(tmp_path, state, "2026-09-24T07:03:00Z", [LIVE[1], LIVE[2]], rows=ROWS)["offer"]["candidates"]


def test_each_excluded_entry_is_logged_once(tmp_path, monkeypatch):
    state = _clocked(tmp_path, monkeypatch, LIVE)
    with close_intent.stopping(*KEY) as mark:
        _tick(tmp_path, state, "2026-09-24T07:02:00Z", [LIVE[1], LIVE[2]])
        mark.settled = True
    log = store.human_log_path(tmp_path).read_text()
    assert log.count("offer_excluded_app_stop") == 1 and "cloude_a" in log


def test_an_unknown_epoch_never_leaves_a_mark():
    with close_intent.stopping("local", "cloude", "cloude_zz", None):
        pass
    close_intent.keep_stopped("local", "cloude", "cloude_zz", None)
    assert not any(k[2] == "cloude_zz" for k in close_intent._lingering)
