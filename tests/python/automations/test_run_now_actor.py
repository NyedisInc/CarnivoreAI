from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from contextlib import closing
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_auto_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_auto_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import src.config  # noqa: E402,F401
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import automation_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.automations import gates, run_by, targets  # noqa: E402
from src.core.automations import models as m  # noqa: E402
from src.core.automations.scheduler import NOTE_BY, Scheduler  # noqa: E402
from src.core.automations.store import AutomationStore  # noqa: E402
from src.core.automations.store_schema import storage_for  # noqa: E402
from src.core.db import db_path_for  # noqa: E402
from src.core.mcp import pending, tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from tests.s7_helpers import migrated_connection  # noqa: E402

ACTION = {"kind": "command", "command": "true"}
PANE = AgentCaller("ses_a", "cloude_a", "ses_a")


async def _runner(ctx, automation, run):
    return m.RunOutcome()


@pytest.fixture
def world(tmp_path, monkeypatch):
    from src.config import settings

    for kind in m.TARGET_KINDS:
        monkeypatch.setitem(targets.RUNNERS, kind, _runner)
    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    db = db_path_for(state)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, origin, "
                     "lifecycle, agent_type, agent_family, created_at, updated_at, title) VALUES "
                     "('sess-1','cloude','cloude_a',1,'/w','created','stopped','claude','claude','t','t','fix login')")
        conn.commit()
    monkeypatch.setattr(run_by, "main_db_path", lambda: db)
    store = AutomationStore(storage_for(tmp_path), notify=lambda topic: None)
    scheduler = Scheduler(SimpleNamespace(), store)
    app = FastAPI()
    app.include_router(automation_routes.router)
    app.dependency_overrides[require_auth] = lambda: None
    app.state.automation_store = store
    app.state.automation_scheduler = scheduler
    mcp_state = tmp_path / "mcp_state"
    mcp_state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: mcp_state, raising=True)
    monkeypatch.setattr(settings, "auth_config_file", str(tmp_path / "config.json"), raising=False)
    monkeypatch.setattr(settings, "_auth_config_cache", None, raising=False)
    monkeypatch.setattr(pending, "_store", pending.PendingActions())
    monkeypatch.setattr(pending, "MAX_WAIT_SECONDS", 0.05)
    auto = store.create(name="nightly", cron="0 3 * * *", target=ACTION)
    return SimpleNamespace(app=app, store=store, scheduler=scheduler, db=db, auto=auto)


def test_the_owner_pressing_run_now_is_kept_in_the_notes_with_the_owners_name(world, monkeypatch):
    from src.core.owner_identity import identity

    monkeypatch.setattr(identity, "os_account_full_name", lambda uid=None: "the owner contributor")
    resp = TestClient(world.app).post(f"/automations/{world.auto['automation_id']}/run")
    assert resp.status_code == 200, resp.text
    run = world.store.run(resp.json()["run_id"])
    assert run["trigger"] == "run_now" and run["notes"][NOTE_BY] == {"kind": "app", "name": "the owner contributor"}


def test_the_owner_name_prefers_the_chosen_display_name_and_invents_none(monkeypatch):
    from src.core.owner_identity import identity

    monkeypatch.setattr(identity, "os_account_full_name", lambda uid=None: None)
    chosen = SimpleNamespace(read=lambda: {"values": {"owner_display_name": "joe"}})
    unset = SimpleNamespace(read=lambda: {"values": {}})
    assert run_by.owner_name(chosen) == "joe"
    assert run_by.owner_name(unset) is None and run_by.owner_name(None) is None
    assert run_by.with_name({"kind": "app"}, None, None) == {"kind": "app"}
    assert run_by.with_name({"kind": "app"}, None, "joe") == {"kind": "app", "name": "joe"}


class View:

    gate_waited = False

    def __init__(self, app):
        self.app = app


def test_an_agent_pressing_run_now_over_mcp_is_named_with_its_session(world):
    held = asyncio.run(tools.call_tool(View(world.app), PANE, "automation_run_now",
                                       {"automation_id": world.auto["automation_id"]}))
    assert "pending" in str(held)
    [item] = pending.get_store().list()
    asyncio.run(pending.get_store().approve(item["id"]))
    [run] = world.store.runs(world.auto["automation_id"])
    by = run["notes"][NOTE_BY]
    assert by["kind"] == "mcp" and by["tmux"] == "cloude_a" and by["session_id"] == "ses_a"
    assert by["name"] == "fix login"


def test_a_skipped_run_now_keeps_who_pressed_it(world, monkeypatch):
    monkeypatch.setattr(gates, "evaluate", lambda *a: (gates.Verdict(m.SKIPPED, m.R_PAUSED), {}))
    run = asyncio.run(world.scheduler.run_now(world.auto["automation_id"], by={"kind": "app"}))
    assert run["status"] == m.SKIPPED and run["notes"] == {NOTE_BY: {"kind": "app"}}


def test_a_scheduled_run_has_no_by(world):
    async def go():
        run = await world.scheduler.run_now(world.auto["automation_id"])
        await asyncio.gather(*world.scheduler._tasks)
        return world.store.run(run["run_id"])

    assert NOTE_BY not in (asyncio.run(go()).get("notes") or {})


def test_with_name_reads_the_session_once_and_falls_back_to_the_client(world):
    assert run_by.with_name({"kind": "app"}, world.db) == {"kind": "app"}
    assert run_by.with_name({"kind": "mcp", "tmux": "cloude_a"}, world.db)["name"] == "fix login"
    token = {"kind": "mcp", "tmux": "mcp-token:7", "client": "my laptop"}
    assert run_by.with_name(token, world.db)["name"] == "my laptop"
    assert "name" not in run_by.with_name({"kind": "mcp", "tmux": "gone"}, world.db)
    assert "name" not in run_by.with_name({"kind": "mcp", "tmux": "cloude_a"}, world.db.parent / "missing.db")
