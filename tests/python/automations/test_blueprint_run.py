from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

import src.config  # noqa: F401
from src.api import automation_listing, blueprints_launch, blueprints_routes, session_sleep_routes
from src.core.automations import models as m
from src.core.automations import run_sessions, targets
from src.core.automations.scheduler import Context
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.automations.targets import blueprint
from src.cplugs.sdk import turn_events
from src.models import Session, SessionInfo
from src.models.blueprints_launch import LaunchedSession

TARGET = {"kind": "blueprint_launch", "blueprint_uuid": "bp-1", "members": None}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setitem(targets.RUNNERS, "blueprint_launch", blueprint.run)
    monkeypatch.setitem(targets.VALIDATORS, "blueprint_launch", lambda target: None)
    store = AutomationStore(storage_for(tmp_path))
    run_sessions._marks.clear(), run_sessions._by_ses_id.clear(), run_sessions._seen_working.clear()
    seen: Dict[str, Any] = {"existing": [], "slept": [], "killed": [], "stored": {}, "status": {}}

    async def fake_call(operation, *args, **kwargs):
        return SimpleNamespace(spec=SimpleNamespace(sessions=[SimpleNamespace(label="a"), SimpleNamespace(label="b")]))

    async def fake_launch(request, index, member, root, consents, cols, rows, existing=None):
        seen["existing"].append(existing)
        tag = f"{len(seen['existing'])}"
        return SimpleNamespace(state="launched", problem=None, session=LaunchedSession(
            id=f"ses_{tag}", tmux_session=f"carnivore_{tag}", session_row_id=100 + int(tag), session_uuid=f"uuid-{tag}"))

    async def fake_sleep(app_state, session_uuid, *, source, fresh_ok):
        seen["slept"].append(session_uuid)
        seen["stored"][session_uuid] = "asleep"
        return SimpleNamespace(status="asleep", code=None)

    async def fake_kill(request, session_uuid, confirm_name=None):
        seen["killed"].append(session_uuid)

    class Manager:
        async def list_session_infos(self):
            return [SessionInfo(session=Session(id=f"ses_{u}", working_dir="/w"), session_row_id=int(u.split("-")[1]) + 100,
                                activity_status=s) for u, s in seen["status"].items()]

    monkeypatch.setattr(blueprints_routes, "call", fake_call)
    monkeypatch.setattr(blueprints_launch, "launch_member", fake_launch)
    monkeypatch.setattr(blueprints_launch, "worktree_root", lambda: "/tmp/wt")
    monkeypatch.setattr(session_sleep_routes, "sleep_by_uuid", fake_sleep)
    monkeypatch.setattr(session_sleep_routes, "kill_asleep_session", fake_kill)
    monkeypatch.setattr(run_sessions, "_stored_state", lambda row_id, uuid: seen["stored"].get(uuid, "live"))
    app_state = SimpleNamespace(session_manager=Manager())
    return SimpleNamespace(store=store, seen=seen, app_state=app_state, ctx=Context(app_state, store, "boot"))


def _start(env, name="nightly"):
    automation = env.store.create(name=name, cron="0 7 * * *", target=TARGET, enabled=False)
    run = env.store.insert_run(automation["automation_id"], "boot")
    return automation, env.store.update_run(run["run_id"], status=m.RUNNING, started_at=time.time())


def test_blueprint_run(env):
    automation, run = _start(env)

    async def go():
        run_sessions.subscribe(env.app_state, env.store)
        try:
            outcome = await blueprint.run(env.ctx, automation, run)
            assert env.seen["existing"] == [None, None] and outcome.status == m.RUNNING and len(outcome.sessions) == 2
            assert len(env.store.run_session_rows(run["run_id"])) == 2

            infos = [SessionInfo(session=Session(id=f"ses_{n}", working_dir="/w"), session_row_id=100 + n) for n in (1, 2, 3)]
            automation_listing.mark_automation(env.app_state, infos)
            assert [i.automation.run_id if i.automation else None for i in infos] == [run["run_id"], run["run_id"], None]
            assert infos[0].automation.name == "nightly" and not hasattr(infos[0].session, "automation")

            for _ in range(2):
                turn_events.publish_turn_end("ses_1")
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                await asyncio.gather(*list(run_sessions._tasks))
            assert env.seen["slept"] == ["uuid-1"]

            env.seen["status"]["uuid-2"] = "working"
            await run_sessions.sweep(env.app_state, env.store)
            assert env.seen["slept"] == ["uuid-1"] and env.store.run(run["run_id"])["status"] == m.RUNNING
            env.seen["status"]["uuid-2"] = "finished_unread"
            await run_sessions.sweep(env.app_state, env.store)
            assert env.seen["slept"] == ["uuid-1", "uuid-2"] and env.store.run(run["run_id"])["status"] == m.SUCCEEDED
        finally:
            run_sessions.unsubscribe()

    asyncio.run(go())


def test_retention_keeps_newest_three(env):
    automation = env.store.create(name="nightly", cron="0 7 * * *", target=TARGET, enabled=False)
    runs = []
    for n in range(1, 5):
        run = env.store.insert_run(automation["automation_id"], "boot")
        for tag in ([f"old-asleep-{n}", f"old-live-{n}"] if n == 1 else [f"s{n}"]):
            env.store.add_run_sessions(run["run_id"], [{"session_uuid": tag, "session_row_id": None, "member_index": 0}])
            env.seen["stored"][tag] = "live" if tag.startswith("old-live") else "asleep"
            env.store.mark_run_session(run["run_id"], tag, slept=env.seen["stored"][tag] == "asleep")
        env.store.update_run(run["run_id"], status=m.SUCCEEDED, ended_at=1.0)
        runs.append(run)
    rows = env.store.active_run_sessions()
    assert len({r["run_id"] for r in rows}) == 4 and len(rows) == 5

    asyncio.run(run_sessions.sweep(env.app_state, env.store))
    assert env.seen["killed"] == ["old-asleep-1"]
    left = {r["session_uuid"] for r in env.store.active_run_sessions()}
    assert "old-live-1" in left and "old-asleep-1" not in left and {"s2", "s3", "s4"} <= left
