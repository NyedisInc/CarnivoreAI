from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core.attention import wiring_builders
from src.core.attention.ledger import AttentionLedger
from src.core.attention.watcher import AttentionWatcher, WatchTarget


def _watcher(targets, on_pass_end, list_targets=None):
    return AttentionWatcher(
        list_targets=list_targets or (lambda: targets), read_evidence=lambda target, now: None,
        raise_toast=MagicMock(), set_unread=MagicMock(), on_busy_edge=MagicMock(),
        ledger=AttentionLedger(), on_pass_end=on_pass_end,
    )


@pytest.mark.asyncio
async def test_pass_end_runs_once_for_a_pass_of_many_targets():
    calls: list[int] = []
    targets = [WatchTarget(f"ses_{n}", f"k{n}") for n in range(5)]
    await _watcher(targets, lambda: calls.append(1)).tick_once()
    assert calls == [1]


@pytest.mark.asyncio
async def test_pass_end_runs_when_the_target_list_is_unreadable_and_a_raise_is_contained():
    def boom() -> list:
        raise OSError("listing down")

    calls: list[int] = []
    await _watcher([], lambda: calls.append(1), list_targets=boom).tick_once()
    assert calls == [1]

    def failing() -> None:
        raise ValueError("sweep broke")

    assert await _watcher([WatchTarget("ses_1", "k1")], failing).tick_once() == 0


def test_the_sweeps_moved_out_of_on_observation(monkeypatch):
    monkeypatch.setattr(wiring_builders, "to_display", lambda *a, **k: "idle")
    monkeypatch.setattr(wiring_builders.session_change_notice, "publish_attention_status", lambda *a, **k: None)
    manager = SimpleNamespace(_registry=SimpleNamespace(sessions={"s": 1}), _is_unread=lambda *a: False)
    effects = MagicMock()
    effects.instance_for.return_value = (None, None)
    hooks = wiring_builders.ObservationHooks(*(MagicMock() for _ in range(7)))
    memos = wiring_builders.ObservationMemos()
    on_observation = wiring_builders.make_on_observation(manager, SimpleNamespace(), effects, hooks, None, memos)
    verdict = SimpleNamespace(state="idle", reason="r", tier=0, activity_hint=None)
    evidence = SimpleNamespace(subagents=None, timers=None, skills=None, parked_work=None, background_open=None,
                               transcript=SimpleNamespace(mcp_events=(), verdict="unread"),
                               registry=SimpleNamespace(known=False), agent_family="claude",
                               identity=SimpleNamespace(tmux_name=None))
    on_observation(SimpleNamespace(session_id="gone", key="k"),
                   SimpleNamespace(evidence=evidence, verdict=verdict, stale=False, observed_at=0))
    hooks.inbox.refresh.assert_not_called()
    hooks.auto_answer.forget.assert_not_called()
    assert "gone" in memos.published and "gone" in memos.marks

    wiring_builders.make_on_pass_end(manager, hooks, memos)()
    hooks.inbox.refresh.assert_called_once()
    hooks.auto_answer.forget.assert_called_once()
    assert "gone" not in memos.published and "gone" not in memos.marks


@pytest.mark.asyncio
async def test_a_targeted_pass_fires_pass_end_exactly_once():
    calls: list[int] = []
    targets = [WatchTarget("ses_1", "k1"), WatchTarget("ses_2", "k2")]
    watcher = _watcher(targets, lambda: calls.append(1))
    await watcher.tick_once()
    calls.clear()
    await watcher.tick_sessions({"ses_1", "ses_2"})
    assert calls == [1]


def _pass_end_parts(refresh):
    manager = SimpleNamespace(_registry=SimpleNamespace(sessions={"live": 1}))
    hooks = wiring_builders.ObservationHooks(*(MagicMock() for _ in range(7)))
    hooks.inbox.refresh.side_effect = refresh
    memos = wiring_builders.ObservationMemos(published={"gone": (1,)}, marks={"gone": (2,)})
    return wiring_builders.make_on_pass_end(manager, hooks, memos), memos, hooks


@pytest.fixture()
def sweep_logs(monkeypatch):
    import structlog
    from structlog.testing import LogCapture

    capture = LogCapture()
    private = structlog.wrap_logger(None, processors=[capture], wrapper_class=structlog.make_filtering_bound_logger(0))
    monkeypatch.setattr(wiring_builders, "logger", private)
    return capture.entries


def test_one_failing_sweep_does_not_starve_the_others_and_warns_once(sweep_logs):
    def boom() -> bool:
        raise RuntimeError("inbox down")

    on_pass_end, memos, hooks = _pass_end_parts(boom)
    hooks.auto_answer.forget.side_effect = ValueError("engine down")
    on_pass_end()
    on_pass_end()
    assert memos.published == {} and memos.marks == {}, "the prune ran although later sweeps raise"
    assert hooks.inbox.refresh.call_count == 2, "refresh runs last and still runs"
    levels = [(e["sweep"], e["log_level"]) for e in sweep_logs if e["event"] == "attention_pass_sweep_failed"]
    assert levels == [("auto_answer_forget", "warning"), ("inbox_refresh", "warning"),
                      ("auto_answer_forget", "debug"), ("inbox_refresh", "debug")]
