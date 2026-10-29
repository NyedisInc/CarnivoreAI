
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import one_shot_routes
from src.cplugs.host import capabilities, runtime, session_actions
from src.cplugs.huddle import fire, held, schedule, service, triggers
from src.core.session_delivery import bring_up as session_bring_up
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.huddle.roles import lead
from src.cplugs.huddle.roles.store import RoleStore
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note, row  # noqa: F401

LISTS = "/api/v1/cplugs/huddle/lists"
ITEMS = "/api/v1/cplugs/huddle/items"
CALLER = AgentCaller("ses_1", "cloude_a", "ses_1")


def iso(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).astimezone().isoformat()


class Env:

    def __init__(self, app, monkeypatch) -> None:
        self.app = app
        self.host = runtime.host_for(app)
        self.ctx = self.host.context("huddle", background=True)
        self.pasted: list = []
        self.woke: list = []
        self.started: list = []
        self.asleep_rows: list = []
        app.state.session_manager._boot_readopt_task = None

        async def paste(request, session_id, text):
            self.pasted.append((session_id, text))
            return SimpleNamespace(pasted_bytes=len(text), submitted=True)

        monkeypatch.setattr(one_shot_routes, "paste_through_gates", paste)
        monkeypatch.setattr(session_bring_up, "READY_STEP_S", 0.02)
        monkeypatch.setattr(held, "POLL_S", 0.02)

    @property
    def store(self):
        return service.store(self.ctx)

    def add(self, client, list_key="12", text="check the build") -> dict:
        return client.post(f"{LISTS}/{list_key}/items", json={"text": text}).json()

    def overdue(self, item_id: int) -> None:
        with self.ctx.storage.connect(True) as conn:
            conn.execute("UPDATE work_item_triggers SET fire_at = ? WHERE item_id = ?", (datetime.now().timestamp() - 5, item_id))

    def trigger(self, item_id: int):
        return self.store.item(item_id)["start_trigger"]

    def set_rows(self, rows) -> None:
        async def infos():
            return rows

        self.app.state.session_manager.list_session_infos = infos


@pytest.fixture
def env(app, monkeypatch):
    rig = Env(app, monkeypatch)
    yield rig
    held.reset()
    schedule.stop()


def arm(client, item_id: int, seconds: float = 60) -> dict:
    return client.patch(f"{ITEMS}/{item_id}", json={"fire_at": iso(seconds)})


def test_the_trigger_fires_once_at_its_time(client, env):
    note(env.app, "ses_new", "12", 100.0)
    RoleStore(env.store).set_lead("12", "ses_new", lead.BY_OWNER)
    item = env.add(client)

    async def scenario():
        scheduler = schedule.Scheduler(env.ctx)
        task = asyncio.create_task(scheduler.run())
        await asyncio.sleep(0.05)
        assert env.pasted == [] and not task.done()
        await asyncio.to_thread(lambda: env.store.update(item["id"], actor="joe", fire_at=iso(0.4)))
        scheduler.nudge()
        await asyncio.sleep(0.2)
        assert env.pasted == []
        for _ in range(100):
            if env.pasted:
                break
            await asyncio.sleep(0.03)
        assert len(env.pasted) == 1
        await asyncio.sleep(0.4)
        task.cancel()

    asyncio.run(scenario())
    target, text = env.pasted[0]
    assert target == "ses_new" and "scheduled swarm came due" in text and f"item {item['id']}" in text
    assert "check the build" in text and "task_manager_changes" in text and "\n" not in text
    fired = env.trigger(item["id"])
    assert fired["fired_at"] is not None and fired["last_error"] is None


def test_an_overdue_trigger_fires_once_after_a_restart(client, env):
    note(env.app, "ses_new", "12", 100.0)
    item = env.add(client)
    assert arm(client, item["id"]).status_code == 200
    env.overdue(item["id"])

    async def boot():
        task = asyncio.create_task(schedule.Scheduler(env.ctx).run())
        await asyncio.sleep(0.3)
        task.cancel()

    asyncio.run(boot())
    assert len(env.pasted) == 1
    asyncio.run(boot())
    assert len(env.pasted) == 1
    assert asyncio.run(schedule.Scheduler(env.ctx).fire_due()) == 0


def test_two_passes_racing_claim_a_trigger_once(client, env):
    item = env.add(client)
    arm(client, item["id"])
    env.overdue(item["id"])
    first = env.store.claim_due_triggers()
    second = env.store.claim_due_triggers()
    assert [i["id"] for i in first] == [item["id"]] and second == []


def test_set_change_cancel_and_the_checks(client, env):
    item = env.add(client)
    assert item["start_trigger"] is None
    a = arm(client, item["id"], 3600).json()
    assert a["start_trigger"]["kind"] == "at" and a["start_trigger"]["fired_at"] is None
    first = a["start_trigger"]["fire_at"]
    b = arm(client, item["id"], 7200).json()
    assert b["start_trigger"]["fire_at"] > first and b["revision"] > a["revision"]
    assert env.store.next_trigger_due() == b["start_trigger"]["fire_at"]
    same = client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": b["start_trigger"]["fire_at_iso"]}).json()
    assert same["revision"] == b["revision"]
    for bad in ("tomorrow", "2026-10-06T15:00:00", iso(-30)):
        assert client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": bad}).status_code == 400, bad
    cleared = client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": ""}).json()
    assert cleared["start_trigger"] is None and env.store.next_trigger_due() is None


def test_changing_a_fired_trigger_re_arms_it(client, env):
    note(env.app, "ses_new", "12", 100.0)
    item = env.add(client)
    arm(client, item["id"])
    env.overdue(item["id"])
    asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    assert env.trigger(item["id"])["fired_at"] is not None
    again = arm(client, item["id"], 30).json()["start_trigger"]
    assert again["fired_at"] is None and again["last_error"] is None


def test_approve_and_delete_cancel_the_trigger(client, env):
    a, b = env.add(client, text="a"), env.add(client, text="b")
    arm(client, a["id"])
    arm(client, b["id"])
    assert client.patch(f"{ITEMS}/{a['id']}", json={"approved": True}).json()["start_trigger"] is None
    assert client.delete(f"{ITEMS}/{b['id']}").status_code == 200
    assert env.store.next_trigger_due() is None
    assert client.patch(f"{ITEMS}/{a['id']}", json={"fire_at": iso(60)}).status_code == 400
    assert asyncio.run(schedule.Scheduler(env.ctx).fire_due()) == 0 and env.pasted == []


def test_a_one_time_fire_on_a_back_burner_item_takes_it_off_and_fires(client, env):
    note(env.app, "ses_new", "12", 100.0)
    item = env.add(client)
    arm(client, item["id"])
    client.patch(f"{ITEMS}/{item['id']}", json={"state": "todo"})
    env.overdue(item["id"])
    assert asyncio.run(schedule.Scheduler(env.ctx).fire_due()) == 1
    assert len(env.pasted) == 1
    assert env.trigger(item["id"])["last_error"] is None


def test_an_asleep_project_session_is_woken_then_told_by_id(client, env, monkeypatch):
    env.set_rows([row("ses_other", 99)])
    item = env.add(client)

    async def asleep():
        return [{"session_uuid": "uuid-1", "project_id": 12, "name": "carnivore"}]

    async def wake(request, uuid):
        env.woke.append(uuid)
        woken = row("ses_woken", 12)
        woken.session_row_id = 5
        env.set_rows([row("ses_other", 99), woken])
        return {"status": "started", "detail": None, "code": None}

    monkeypatch.setattr(session_actions, "asleep", lambda request: asleep())
    monkeypatch.setattr(session_actions, "wake", wake)
    monkeypatch.setattr(session_actions, "start", lambda request, pid: pytest.fail("a sleeping session is woken, not replaced"))
    monkeypatch.setattr(capabilities, "session_uuids", lambda ids: {5: "uuid-1"})
    arm(client, item["id"])
    env.overdue(item["id"])
    assert asyncio.run(schedule.Scheduler(env.ctx).fire_due()) == 1
    assert env.woke == ["uuid-1"]
    assert [t for t, _ in env.pasted] == ["ses_woken"] and "came due" in env.pasted[0][1]
    assert env.trigger(item["id"])["last_error"] is None


def test_no_session_at_all_starts_one_then_tells_it(client, env, monkeypatch):
    env.set_rows([])
    item = env.add(client)

    async def asleep():
        return []

    async def start(request, project_id):
        env.started.append(project_id)
        env.set_rows([row("ses_fresh", 12)])
        return "ses_fresh"

    monkeypatch.setattr(session_actions, "asleep", lambda request: asleep())
    monkeypatch.setattr(session_actions, "start", start)
    arm(client, item["id"])
    env.overdue(item["id"])
    assert asyncio.run(schedule.Scheduler(env.ctx).fire_due()) == 1
    assert env.started == [12] and [t for t, _ in env.pasted] == ["ses_fresh"]


def test_a_failed_start_is_kept_on_the_row_and_not_retried(client, env, monkeypatch):
    env.set_rows([])
    item = env.add(client)

    async def asleep():
        return []

    async def start(request, project_id):
        raise HTTPException(status_code=502, detail="agent failed to launch")

    monkeypatch.setattr(session_actions, "asleep", lambda request: asleep())
    monkeypatch.setattr(session_actions, "start", start)
    arm(client, item["id"])
    env.overdue(item["id"])
    asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    trigger = env.trigger(item["id"])
    assert "agent failed to launch" in trigger["last_error"] and trigger["fired_at"] is not None
    assert asyncio.run(schedule.Scheduler(env.ctx).fire_due()) == 0 and env.pasted == []


def test_the_shared_list_with_no_agent_session_fails_with_a_sentence(client, env):
    env.set_rows([])
    item = env.add(client, list_key="all")
    arm(client, item["id"])
    env.overdue(item["id"])
    asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    assert "shared list" in env.trigger(item["id"])["last_error"]


def test_a_session_that_never_reaches_its_prompt_is_an_error_not_a_hang(client, env, monkeypatch):
    env.set_rows([])
    item = env.add(client)
    monkeypatch.setattr(session_bring_up, "READY_TIMEOUT_S", 0.1)

    async def asleep():
        return []

    async def start(request, project_id):
        busy = row("ses_busy", 12)
        busy.activity_status = "working"
        env.set_rows([busy])
        return "ses_busy"

    monkeypatch.setattr(session_actions, "asleep", lambda request: asleep())
    monkeypatch.setattr(session_actions, "start", start)
    arm(client, item["id"])
    env.overdue(item["id"])
    asyncio.run(schedule.Scheduler(env.ctx).fire_due())
    assert "did not reach its prompt" in env.trigger(item["id"])["last_error"] and env.pasted == []


def test_a_busy_session_holds_the_scheduled_tell_with_its_words(client, env, monkeypatch):
    note(env.app, "ses_new", "12", 100.0)
    item = env.add(client)
    calls = []

    async def paste(request, session_id, text):
        calls.append(text)
        if len(calls) == 1:
            raise HTTPException(status_code=409, detail={"code": "pane_dialog_open", "message": "a dialog is open"})
        return SimpleNamespace(pasted_bytes=len(text), submitted=True)

    monkeypatch.setattr(one_shot_routes, "paste_through_gates", paste)

    async def scenario():
        arm(client, item["id"])
        env.overdue(item["id"])
        await schedule.Scheduler(env.ctx).fire_due()
        await asyncio.sleep(0.3)

    asyncio.run(scenario())
    assert len(calls) >= 2 and all("came due" in c for c in calls) and held.snapshot() == []


def call(app, name, args):
    host = SimpleNamespace(app=app, gate_waited=True, list_session_infos=app.state.session_manager.list_session_infos)
    result = asyncio.run(tools.call_tool(host, CALLER, name, {"lean": False, **args} if name != "task_manager_batch_run" else args))
    text = result["content"][0]["text"]
    return (False, text) if result.get("isError") else (True, json.loads(text))


def test_claude_sets_and_cancels_fire_at_with_huddle_update_and_the_batch(client, env):
    item = env.add(client)
    ok, set_ = call(env.app, "task_manager_update", {"item": item["id"], "fire_at": iso(3600)})
    assert ok and set_["start_trigger"]["kind"] == "at" and "fire_at_iso" in set_["start_trigger"]
    assert env.store.next_trigger_due() is not None
    ok, cleared = call(env.app, "task_manager_update", {"item": item["id"], "fire_at": ""})
    assert ok and "start_trigger" not in cleared and env.store.next_trigger_due() is None
    ok, text = call(env.app, "task_manager_update", {"item": item["id"], "fire_at": "next tuesday"})
    assert not ok and "fire_at" in text
    ok, batch = call(env.app, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "update", "item_id": item["id"], "fire_at": iso(1800)}]})
    assert ok and batch["applied"] == 1
    assert env.trigger(item["id"])["kind"] == "at"
    defn = next(d for d in tools.tool_definitions() if d["name"] == "task_manager_update")
    assert "fire_at" in defn["inputSchema"]["properties"]


def test_add_and_batch_add_take_fire_at_and_a_bad_time_makes_no_item(client, env):
    ok, added = call(env.app, "task_manager_add", {"list": "12", "text": "ping me", "fire_at": iso(3600)})
    assert ok and env.trigger(added["id"])["kind"] == "at" and env.store.next_trigger_due() is not None
    ok, batch = call(env.app, "task_manager_batch_run", {"list_id": "12", "ops": [
        {"op": "add", "text": "batched", "fire_at": iso(1800)}, {"op": "add", "text": "plain"}]})
    assert ok and batch["applied"] == 2
    scheduled = [i for i in env.store.list_items("12")["items"] if i["text"] == "batched"]
    assert len(scheduled) == 1 and env.trigger(scheduled[0]["id"])["kind"] == "at"
    before = len(env.store.list_items("12")["items"])
    for bad in ("next tuesday", "2030-01-01T10:00:00", iso(-60)):
        ok, text = call(env.app, "task_manager_add", {"list": "12", "text": "nope", "fire_at": bad})
        assert not ok and "fire_at" in text
    ok, batch = call(env.app, "task_manager_batch_run", {"list_id": "12", "ops": [{"op": "add", "text": "x", "fire_at": "bogus"}]})
    assert ok and batch["failed"] == 1
    assert len(env.store.list_items("12")["items"]) == before
    defn = next(d for d in tools.tool_definitions() if d["name"] == "task_manager_add")
    assert "fire_at" in defn["inputSchema"]["properties"]


def test_pushing_a_trigger_change_tells_the_scheduler(client, env):
    seen = []
    off = triggers.subscribe(lambda: seen.append(1))
    try:
        item = env.add(client)
        arm(client, item["id"])
        client.patch(f"{ITEMS}/{item['id']}", json={"fire_at": ""})
        client.delete(f"{ITEMS}/{item['id']}")
    finally:
        off()
    assert len(seen) == 3


def test_only_an_owner_bound_context_can_message_wake_or_start(app):
    host = runtime.host_for(app)
    plain = host.context("huddle")
    for name in ("message", "wake", "start", "asleep", "booted"):
        assert not hasattr(plain.sessions, name), name
    bound = host.context("huddle", background=True)
    for name in ("message", "wake", "start", "asleep", "booted"):
        assert callable(getattr(bound.sessions, name)), name
