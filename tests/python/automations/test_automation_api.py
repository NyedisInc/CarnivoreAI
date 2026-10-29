from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_auto_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_auto_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import src.config  # noqa: E402,F401
from fastapi import FastAPI  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import automation_routes, automation_run_routes, routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.automations import models as m  # noqa: E402
from src.core.automations import targets  # noqa: E402
from src.core.automations.store import AutomationStore  # noqa: E402
from src.core.automations.store_schema import storage_for  # noqa: E402
from src.core.mcp import pending, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from src.core.resource_push import topics  # noqa: E402
from src.models.automations import UNATTENDED_PHRASE  # noqa: E402

BASE = datetime(2027, 1, 5, 12, 0, tzinfo=timezone.utc).timestamp()
CARD = {"kind": "swarm_card", "project_id": 1, "title": "t", "summary": "s"}
AGENT = {"kind": "agent", "folder": "/tmp/x", "prompt": "hi", "permission": "read_only"}
PANE = AgentCaller("ses_a", "cloude_a", "ses_a")


async def _runner(ctx, automation, run):
    return m.RunOutcome()


@pytest.fixture
def world(tmp_path, monkeypatch):
    from src.config import settings

    for kind in m.TARGET_KINDS:
        monkeypatch.setitem(targets.RUNNERS, kind, _runner)
    clock = SimpleNamespace(now=BASE)
    announced: list = []
    store = AutomationStore(storage_for(tmp_path), clock=lambda: clock.now, notify=announced.append)
    app = FastAPI()
    app.include_router(automation_routes.router)
    app.include_router(automation_run_routes.router)
    app.state.automation_store = store
    state = tmp_path / "mcp_state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    return SimpleNamespace(app=app, store=store, clock=clock, announced=announced)


def test_every_route_needs_auth_and_is_registered(world):
    routers = (automation_routes.router, automation_run_routes.router)
    paths = [(method, r.path) for router in routers for r in router.routes if isinstance(r, APIRoute) for method in r.methods]
    assert len(paths) >= 12, paths
    client = TestClient(world.app)
    for method, path in paths:
        url = path.replace("{automation_id}", "x").replace("{run_id}", "x").replace("{finding_id}", "x")
        assert client.request(method, url, json={}).status_code == 401, (method, path)
    whole = FastAPI()
    whole.include_router(routes.router)
    documented = whole.openapi()["paths"]
    assert all(any(key.endswith(path) for key in documented) for _method, path in paths)


def test_floor_phrase_and_run_routes(world):
    world.app.dependency_overrides[require_auth] = lambda: True
    client = TestClient(world.app)
    ok = client.post("/automations", json={"name": "q", "cron": "*/15 * * * *", "target": CARD})
    assert ok.status_code == 200 and ok.json()["revision"] == 1
    floor = client.post("/automations", json={"name": "fast", "cron": "*/10 * * * *", "target": CARD})
    assert floor.status_code == 422 and floor.json()["detail"]["code"] == "interval_under_15_min"
    agent = {"name": "ag", "cron": "0 7 * * 1", "target": {**AGENT, "permission": "unattended"}}
    bare = client.post("/automations", json=agent)
    assert bare.status_code == 422 and bare.json()["detail"]["code"] == "unattended_not_acknowledged"
    typed = client.post("/automations", json={**agent, "acknowledge_unattended": UNATTENDED_PHRASE})
    assert typed.status_code == 200
    stale = client.patch(f"/automations/{ok.json()['automation_id']}", json={"revision": 9, "enabled": False})
    assert stale.status_code == 409 and stale.json()["detail"]["automation"]["revision"] == 1
    runs = client.get(f"/automations/{ok.json()['automation_id']}/runs")
    assert runs.status_code == 200 and runs.json() == {"runs": []}
    assert client.get("/automations/targets").json()["kinds"]
    assert client.get("/automations").json()["automations"][0]["last_run"] is None


class View:

    gate_waited = False

    def __init__(self, app):
        self.app = app


def _call(view, name, args):
    return asyncio.run(tools.call_tool(view, PANE, name, args))


def test_mcp_refuses_unattended_and_parks_a_full_prompt(world):
    view = View(world.app)
    write_names = {n for n in tools._TOOLS if n.startswith("automation_") and n not in
                   ("automation_get", "automation_runs_list", "automation_run_get", "automation_log", "automation_commands_get",
                    "automation_changes", "automation_scheduler_get")}
    assert len(write_names) == 10 and write_names <= tools.WRITE_TOOLS and "automations_list" in tools._TOOLS
    unattended = {"name": "ag", "cron": "0 7 * * 1", "target": {**AGENT, "permission": "unattended"}}
    refused = _call(view, "automation_create", unattended)
    assert refused.get("isError") and "nothing was done" in refused["content"][0]["text"]
    assert _call(view, "automation_create", {**unattended, "target": AGENT, "acknowledge_unattended": UNATTENDED_PHRASE}).get("isError")
    assert pending.get_store().list() == []
    assert world.store.list_all() == []

    prompt = "p" * 32768
    held = _call(view, "automation_create", {"name": "weekly audit", "cron": "0 7 * * 1", "target": {**AGENT, "prompt": prompt}})
    assert "pending" in str(held)
    items = pending.get_store().list()
    assert len(items) == 1 and items[0]["action"] == "automation_create"
    assert prompt in items[0]["body"]
    assert "weekly audit" in items[0]["plain"] and "read only" in items[0]["plain"]
    assert world.store.list_all() == []
    asyncio.run(pending.get_store().approve(items[0]["id"]))
    saved = world.store.list_all()
    assert len(saved) == 1 and saved[0]["created_by"] == "mcp"


def test_mcp_scheduler_pause_reads_at_once_and_parks_the_switch(world):
    from src.config import settings
    from src.core.mcp import beast_mode

    view = View(world.app)
    config = settings.auth_config_file
    open(config, "w").write('{"keep_me": 1}')
    assert "automation_scheduler_set" not in beast_mode.ALWAYS_WAITS and "automation_scheduler_set" in tools.WRITE_TOOLS
    assert "automation_scheduler_get" not in tools.WRITE_TOOLS
    assert _call(view, "automation_scheduler_get", {})["content"][0]["text"] == '{"paused": false}'
    assert _call(view, "automation_scheduler_set", {"paused": "yes"}).get("isError")
    held = _call(view, "automation_scheduler_set", {"paused": True})
    assert "pending" in str(held)
    items = pending.get_store().list()
    assert len(items) == 1 and items[0]["action"] == "automation_scheduler_set" and "pause every scheduled" in items[0]["plain"]
    assert _call(view, "automation_scheduler_get", {})["content"][0]["text"] == '{"paused": false}'
    asyncio.run(pending.get_store().approve(items[0]["id"]))
    assert _call(view, "automation_scheduler_get", {})["content"][0]["text"] == '{"paused": true}'
    assert '"keep_me": 1' in open(config).read()


def test_every_store_write_announces_its_topic(world):
    store, announced, clock = world.store, world.announced, world.clock
    A, R = {topics.AUTOMATIONS}, {topics.AUTOMATION_RUNS}
    both = A | R
    made = {}

    def fires(label, expected, call):
        announced.clear()
        call()
        assert set(announced) == expected, (label, announced)
        return label

    def create():
        made["a"] = store.create(name="one", cron="*/15 * * * *", target=CARD, misfire="skip", retry_max=1, retry_backoff_s=60)

    done = [
        fires("create", A, create),
        fires("update", A, lambda: store.update(made["a"]["automation_id"], 1, name="uno")),
        fires("set_enabled", A, lambda: store.set_enabled(made["a"]["automation_id"], False)),
        fires("set_enabled_on", A, lambda: store.set_enabled(made["a"]["automation_id"], True)),
    ]
    slot = store.get(made["a"]["automation_id"])["next_fire_at"]
    done.append(fires("claim_due", both, lambda: store.claim_due(slot + 1, "b1")))
    run = store.runs(made["a"]["automation_id"])[0]
    done.append(fires("update_run_live", R, lambda: store.update_run(run["run_id"], status=m.RUNNING)))
    done.append(fires("update_run_terminal", R, lambda: store.update_run(run["run_id"], status=m.SUCCEEDED, ended_at=BASE)))
    later = store.get(made["a"]["automation_id"])["next_fire_at"]
    done.append(fires("claim_due_missed", both, lambda: store.claim_due(later + 3600, "b1")))
    done.append(fires("settle_retry", A, lambda: store.settle_retry(made["a"]["automation_id"], True, BASE)))
    done.append(fires("settle_retry_cleared", set(), lambda: store.settle_retry(made["a"]["automation_id"], False, BASE)))
    done.append(fires("insert_run", R, lambda: made.update(r=store.insert_run(made["a"]["automation_id"], "b1"))))
    done.append(fires("add_run_sessions", set(), lambda: store.add_run_sessions(
        made["r"]["run_id"], [{"session_uuid": "u1", "session_row_id": 1, "member_index": 0}])))
    done.append(fires("mark_run_session", set(), lambda: store.mark_run_session(made["r"]["run_id"], "u1", slept=True)))
    done.append(fires("reconcile_boot", R, lambda: store.reconcile_boot("b2")))
    skipped = store.insert_run(made["a"]["automation_id"], "b2")
    done.append(fires("finish_skip", R, lambda: store.finish_skip(skipped["run_id"], m.R_DISABLED)))
    done.append(fires("delete", both, lambda: store.delete(made["a"]["automation_id"])))
    assert len(done) >= 10
    writers = {n for n, f in inspect.getmembers(AutomationStore, inspect.isfunction)
               if not n.startswith("_") and ("self._write(" in inspect.getsource(f) or "self.update(" in inspect.getsource(f))}
    assert writers == {"create", "update", "set_enabled", "delete", "claim_due", "finish_skip", "insert_run", "update_run",
                       "reconcile_boot", "add_run_sessions", "mark_run_session", "settle_retry"}, writers
    assert writers <= {d.split("_on")[0].split("_live")[0].split("_terminal")[0].split("_missed")[0] for d in done}


def test_recent_runs_route_lists_every_automations_runs_with_names(world):
    client = TestClient(world.app)
    assert client.get("/automations/runs").status_code == 401
    world.app.dependency_overrides[require_auth] = lambda: True
    first = world.store.create(name="alpha", cron="*/15 * * * *", target=CARD)
    second = world.store.create(name="beta", cron="0 7 * * 1", target=CARD)
    assert client.get("/automations/runs").json() == {"runs": [], "total": 0, "next_before": None}
    a = world.store.insert_run(first["automation_id"], "boot1")
    b = world.store.insert_run(second["automation_id"], "boot1")
    world.store.update_run(a["run_id"], status=m.SUCCEEDED, ended_at=BASE)
    runs = client.get("/automations/runs").json()["runs"]
    assert [(r["automation_name"], r["status"]) for r in runs] == [("beta", b["status"]), ("alpha", m.SUCCEEDED)]
    assert all("report" not in r for r in runs)
    assert len(client.get("/automations/runs?limit=1").json()["runs"]) == 1
    assert client.get("/automations/runs?limit=0").status_code == 422
    over_mcp = _call(View(world.app), "automation_runs_list", {})
    assert not over_mcp.get("isError") and "beta" in over_mcp["content"][0]["text"]
