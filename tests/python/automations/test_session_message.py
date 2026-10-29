
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import src.config  # noqa: F401
from src.api import one_shot_routes
from src.core.automations import gates, run_sessions, targets
from src.core.automations import models as m
from src.core.automations.scheduler import Scheduler
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.automations.targets import session_message
from src.core.session_delivery import bring_up
from src.cplugs.sdk import turn_events

UUID = "0f6c2d6e-1111-4c4c-9e9e-000000000001"
TARGET = {"kind": "session_message", "session_uuid": UUID, "text": "run the weekly checks", "project_id": 3}


class Ops:

    def __init__(self, state: str, status: str = "idle") -> None:
        self.state, self.status, self.calls = state, status, []

    async def list(self):
        if self.state != "live":
            return []
        return [SimpleNamespace(tmux_session=None, session=SimpleNamespace(id="ses_1"), activity_status=self.status, session_row_id=1)]

    async def durable_keys(self, infos=None):
        return {"ses_1": UUID}

    async def asleep(self):
        return [{"session_uuid": UUID, "project_id": 3, "name": "x"}] if self.state == "asleep" else []

    async def wake(self, session_uuid):
        self.calls.append(("wake", session_uuid))
        self.state = "live"
        return {"status": "started", "detail": None, "code": None}

    async def start(self, project_id):
        self.calls.append(("start", project_id))
        self.state = "live"
        return "ses_1"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setitem(targets.RUNNERS, "session_message", session_message.run)
    monkeypatch.setitem(targets.VALIDATORS, "session_message", lambda t: None)
    monkeypatch.setattr(bring_up, "READY_STEP_S", 0.01)
    monkeypatch.setattr(session_message, "QUEUE_STEP_S", 5.0)
    monkeypatch.setattr("src.core.automations.notify_policy.tell", lambda *a, **k: None)
    pasted, w = [], SimpleNamespace(busy=0, ops=None)

    async def paste(request, session_id, text, *, idle_only=False, **_):
        assert idle_only is True
        if w.busy:
            w.busy -= 1
            asyncio.get_running_loop().call_later(0.05, turn_events.publish_turn_end, session_id)
            raise HTTPException(409, detail={"code": "pane_dialog_open"})
        pasted.append((session_id, text))
        return SimpleNamespace(pasted_bytes=len(text), submitted=True)

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", paste)
    monkeypatch.setattr(bring_up, "ops_for_app", lambda app_state: w.ops)
    store = AutomationStore(storage_for(tmp_path), notify=lambda _t: None)
    w.store, w.pasted = store, pasted
    return w


def _run(w, ops, target=TARGET, **extra):
    w.ops = ops
    automation = w.store.create(name=f"m{len(w.pasted)}{ops.state}{len(ops.calls)}", cron="0 7 * * 1", target=target, **extra)
    run = w.store.insert_run(automation["automation_id"], "boot")
    ctx = SimpleNamespace(app_state=SimpleNamespace(), store=w.store, boot_id="boot")
    return asyncio.run(session_message.run(ctx, automation, run)), run


def test_live_session_gets_the_message_and_never_enters_run_sessions(world, monkeypatch):
    world.ops = Ops("live")
    automation = world.store.create(name="married", cron="0 7 * * 1", target=TARGET)
    monkeypatch.setattr(gates, "evaluate", lambda *a: (None, {}))
    slept = []

    async def sleeper(*a, **k):
        slept.append(a)
        return True

    monkeypatch.setattr(run_sessions, "_sleep", sleeper)

    async def go():
        scheduler = Scheduler(SimpleNamespace(), world.store)
        run = await scheduler.run_now(automation["automation_id"])
        await asyncio.gather(*scheduler._tasks)
        await run_sessions.sweep(SimpleNamespace(), world.store)
        return run

    run = asyncio.run(go())
    done = world.store.run(run["run_id"])
    assert world.pasted == [("ses_1", "run the weekly checks")]
    assert done["status"] == m.SUCCEEDED and done["sessions"][0]["session_uuid"] == UUID
    assert world.store.run_session_rows(run["run_id"]) == [] and world.store.active_run_sessions() == []
    assert slept == []


def test_busy_session_queues_until_its_turn_ends(world):
    world.busy = 2
    outcome, _run_row = _run(world, Ops("live", status="working"))
    assert outcome.status == m.SUCCEEDED and outcome.report["delivery"]["attempts"] == 3
    assert outcome.report["delivery"]["queued_s"] < 5.0
    assert world.pasted == [("ses_1", "run the weekly checks")]


def test_asleep_session_is_woken_or_skipped(world):
    ops = Ops("asleep")
    outcome, _ = _run(world, ops)
    assert outcome.status == m.SUCCEEDED and ops.calls == [("wake", UUID)]
    skip, _ = _run(world, Ops("asleep"), {**TARGET, "if_asleep": "skip"})
    assert skip.status == m.SKIPPED and skip.reason == "session_asleep"


def test_gone_session_is_started_in_its_project_or_fails(world):
    ops = Ops("gone")
    outcome, _ = _run(world, ops)
    assert outcome.status == m.SUCCEEDED and ops.calls == [("start", 3)] and outcome.sessions[0]["how"] == "started"
    fail, _ = _run(world, Ops("gone"), {**TARGET, "if_gone": "fail"})
    assert fail.status == m.FAILED and fail.reason == "session_missing"


def test_dead_pane_fails_and_start_without_project_is_refused(world):
    dead, _ = _run(world, Ops("live", status="dead"))
    assert dead.status == m.FAILED and dead.reason == "session_dead" and world.pasted == []
    with pytest.raises(m.AutomationInvalid):
        m.validate_target({k: v for k, v in TARGET.items() if k != "project_id"})
    with pytest.raises(m.AutomationInvalid):
        m.validate_target({**TARGET, "session_uuid": "remote:peer-1"})
