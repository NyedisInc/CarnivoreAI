
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.core.automations import gates, targets
from src.core.automations import models as m
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.automations.targets import sequence

ACTION = {"kind": "recipe", "recipe": "sleep_idle_sessions"}
MESSAGE = {"kind": "session_message", "session_uuid": "1d54c5e7-1c29-4e67-835c-e79ec618ae16", "text": "go", "if_gone": "fail"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    calls, told = [], []
    outcomes = {"recipe": m.RunOutcome(status=m.SUCCEEDED, report={"ok": 1}),
                "session_message": m.RunOutcome(status=m.SUCCEEDED, cost_usd=None)}

    def fake(kind):
        async def runner(ctx, automation, run_row):
            calls.append((kind, automation["delivery"]["notify"]))
            return outcomes[kind]
        return runner

    for kind in ("recipe", "session_message"):
        monkeypatch.setitem(targets.RUNNERS, kind, fake(kind))
    monkeypatch.setitem(targets.RUNNERS, "sequence", sequence.run)
    monkeypatch.setitem(targets.VALIDATORS, "sequence", sequence.validate_target)
    monkeypatch.setattr(sequence, "_tell", lambda type_id, automation, run_id, severity, store=None: told.append(type_id))
    store = AutomationStore(storage_for(tmp_path), notify=lambda _t: None)
    return SimpleNamespace(store=store, calls=calls, told=told, outcomes=outcomes)


def _run(w, steps):
    automation = w.store.create(name=f"s{len(w.calls)}", cron="0 7 * * 1", target={"kind": "sequence", "steps": steps})
    run = w.store.insert_run(automation["automation_id"], "boot")
    ctx = SimpleNamespace(app_state=SimpleNamespace(), store=w.store, boot_id="boot")
    return asyncio.run(sequence.run(ctx, automation, run))


@pytest.mark.parametrize("steps", [
    [MESSAGE, ACTION],
    [ACTION],
    [ACTION] * 5,
    [ACTION, {"kind": "sequence", "steps": [ACTION, ACTION]}],
    [ACTION, {**MESSAGE, "argv": ["x"]}],
])
def test_bad_shapes_are_refused(steps):
    with pytest.raises(m.AutomationInvalid):
        m.validate_target({"kind": "sequence", "steps": steps})


def test_an_action_then_a_message_runs_both_quietly_and_tells_once(world):
    outcome = _run(world, [ACTION, MESSAGE])
    assert outcome.status == m.SUCCEEDED
    assert world.calls == [("recipe", False), ("session_message", False)]
    assert [s["kind"] for s in outcome.report["steps"]] == ["recipe", "session_message"]
    assert world.told == []


def test_a_failed_step_stops_the_sequence_and_is_the_runs_reason(world):
    world.outcomes["recipe"] = m.RunOutcome(status=m.FAILED, reason="auto_sleep_unavailable")
    outcome = _run(world, [ACTION, MESSAGE])
    assert outcome.status == m.FAILED and outcome.reason == "auto_sleep_unavailable"
    assert world.calls == [("recipe", False)]
    assert world.told == ["automation_failed"]


def test_a_sequence_spends_under_its_last_steps_login():
    seq = {"kind": "sequence", "steps": [ACTION, {"kind": "agent", "login_account_id": "claude-work"}]}
    assert gates.spends(seq) is True
    assert gates.spends({"kind": "sequence", "steps": [ACTION, ACTION]}) is False
    from src.core.byoai.native import cli_run

    original = cli_run.profile_dir
    try:
        cli_run.profile_dir = lambda provider, account_id: f"/p/{account_id}"
        assert gates.login_of(seq) == ("claude-work", "/p/claude-work")
    finally:
        cli_run.profile_dir = original
