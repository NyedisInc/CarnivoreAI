
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from src.cplugs.host import runtime, state as owner_state
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from tests.python.cplugs.owner import turn_on

PANE = AgentCaller("ses_1", "cloude_a", "ses_1")


@pytest.fixture
def manager(tmp_path: Path):
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    turn_on(host)

    async def infos():
        return []

    return SimpleNamespace(app=app, gate_waited=True, list_session_infos=infos)


def call(manager, name, args, caller=PANE):
    result = asyncio.run(tools.call_tool(manager, caller, name, args))
    return not result.get("isError"), result["content"][0]["text"]


def set_state(manager, **changes):
    host = runtime.host_for(manager.app)
    d = runtime.find("huddle")
    owner_state.update(host.state_dir, d.manifest, None, lambda st: owner_state.CplugState(st.id, **{
        "enabled": st.enabled, "grants": st.grants, **changes}))


def test_a_read_token_sees_no_cplug_write(manager):
    read = {d["name"] for d in tools.tool_definitions(AgentCaller("x", "x", "x", "tok", "read"))}
    assert "task_manager_tasks_list" in read and "plugins_list" in read
    assert not read & {"task_manager_add", "task_manager_update", "task_manager_ask", "task_manager_reply", "cplug_update"}


def test_a_disabled_cplugs_tools_are_absent_and_refused(manager):
    assert "task_manager_tasks_list" in {d["name"] for d in tools.tool_definitions()}
    set_state(manager, enabled=False)
    assert not {d["name"] for d in tools.tool_definitions()} & {"task_manager_tasks_list", "task_manager_add"}
    ok, text = call(manager, "task_manager_tasks_list", {"list": "all"})
    assert not ok and "disabled" in text


def test_an_agent_write_needs_agent_writes(manager):
    ok, _ = call(manager, "task_manager_add", {"list": "all", "text": "x"})
    assert ok
    set_state(manager, grants=("sessions.read", "notify"))
    ok, text = call(manager, "task_manager_add", {"list": "all", "text": "y"})
    assert not ok and "agent_writes" in text


def test_cplug_update_always_waits_for_the_owner(manager, monkeypatch):
    from src.core.mcp import write_tools

    parked = []

    async def park(manager, caller, target_id, target_tmux, name, summary, shown, run, dedupe_key="", beast_eligible=True):
        parked.append(name)
        return {"content": [{"type": "text", "text": json.dumps({"status": "pending", "id": "act_1"})}]}

    monkeypatch.setattr(write_tools, "park", park)
    ok, text = call(manager, "cplug_update", {"cplug_id": "huddle", "revision": 0, "enabled": False})
    assert ok and json.loads(text)["status"] == "pending" and parked == ["cplug_update"]
    assert runtime.host_for(manager.app).enabled("huddle")


def test_plugins_list_and_its_old_name_answer_the_same_rows_with_an_installed_catalog_plugin(manager):
    from dataclasses import replace
    from contextlib import closing

    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.skills.ledger import InstallLedger
    from tests.test_install_ledger import make_item

    state_dir = runtime.host_for(manager.app).state_dir
    ensure_db_migrated(state_dir, 4, "0.8.2")
    with closing(connect(db_path_for(state_dir))) as conn:
        InstallLedger(conn).insert(replace(make_item(item_id="rea/rea", name="rea"), kind="plugin"))
    ok, new = call(manager, "plugins_list", {})
    old_ok, old = call(manager, "cplugs_list", {})
    assert ok and old_ok and json.loads(new) == json.loads(old)
    rows = json.loads(new)["plugins"]
    assert {"huddle", "rea/rea"} <= {r["id"] for r in rows}
    assert {r["kind"] for r in rows if r["id"] == "rea/rea"} == {"plugin"}
    assert "cplugs_list" in {d["name"] for d in tools.tool_definitions()}
