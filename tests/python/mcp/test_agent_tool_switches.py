
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.config.mcp import McpConfig
from src.core.mcp import agent_tool_switches, aliases, deprecated_tools, instructions, protocol, tool_families, tools
from src.core.mcp.caller import AgentCaller
from tests.python.mcp.test_mcp_endpoint import _call, _hdr, _rpc, env  # noqa: F401

pytestmark = [pytest.mark.real_agent_tool_switches, pytest.mark.real_deprecated_default_off]

PANE = AgentCaller(session_id="ses_a", tmux_name="carnivore_a", current_session_id="ses_a")


@pytest.fixture
def switches(monkeypatch):
    cfg = McpConfig()
    monkeypatch.setattr(agent_tool_switches, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg)))
    return cfg


TASK_MANAGER_FAMILY = ("huddle_", "task_manager_")


def _names(caller=PANE) -> set:
    return {d["name"] for d in tools.tool_definitions(caller)}


def test_a_config_with_neither_key_reads_huddle_off_swarm_on(tmp_path) -> None:
    from src.config.auth_loader import load

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"mcp": {"enabled": True}}))
    block = load(cfg, totp_secret="x", jwt_secret="y").mcp
    assert (block.agent_huddle_tools, block.agent_swarm_tools, block.agent_app_settings_tools) == (False, True, False)
    assert agent_tool_switches.DEFAULTS == agent_tool_switches.AgentToolSwitches(huddle=False, swarm=True, app_settings=False)


def test_defaults_hide_huddle_and_keep_swarm(switches) -> None:
    names = _names()
    assert not any(n.startswith(TASK_MANAGER_FAMILY) for n in names)
    assert sum(n.startswith("swarm_") and n not in tool_families.SWARM_SWITCH_TOOLS for n in names) == 33
    assert "sessions_list" in names


def test_huddle_on_lists_every_huddle_tool(switches) -> None:
    switches.agent_huddle_tools = True
    huddle_tools = {n for n in tools._TOOLS if n.startswith("huddle_")} | {n for n in aliases.table().values() if n.startswith("task_manager_")}
    huddle_tools -= deprecated_tools.DEPRECATED
    assert huddle_tools and huddle_tools <= _names()


def test_swarm_off_hides_every_swarm_tool(switches) -> None:
    switches.agent_huddle_tools = True
    switches.agent_swarm_tools = False
    names = _names()
    assert not any(n.startswith("swarm_") and n not in tool_families.SWARM_SWITCH_TOOLS for n in names)
    assert any(n.startswith("huddle_") for n in names) and "crosstalk_send" in names


def test_an_owner_listing_is_never_filtered(switches) -> None:
    switches.agent_swarm_tools = False
    names = _names(caller=None)
    assert any(n.startswith("huddle_") for n in names) and any(n.startswith("swarm_") for n in names)


def test_a_called_huddle_tool_is_refused_with_the_owner_reason(env, switches) -> None:  # noqa: F811
    client, mgr, _cfg = env
    result = _call(client, mgr, "huddle_list", {})
    assert result["isError"] is True
    assert "owner turned huddle tools off" in result["content"][0]["text"]


def test_a_called_swarm_tool_is_refused_when_swarm_is_off(env, switches) -> None:  # noqa: F811
    client, mgr, _cfg = env
    switches.agent_swarm_tools = False
    result = _call(client, mgr, "swarm_roster", {})
    assert result["isError"] is True
    assert "owner turned swarm tools off" in result["content"][0]["text"]


def test_tools_list_over_the_wire_follows_the_switch(env, switches) -> None:  # noqa: F811
    client, mgr, _cfg = env
    listed = lambda: {t["name"] for t in client.post("/mcp", json=_rpc("tools/list"), headers=_hdr(mgr)).json()["result"]["tools"]}  # noqa: E731
    assert "huddle_list" not in listed() and "task_manager_tasks_list" not in listed()
    switches.agent_huddle_tools = True
    assert "huddle_list" in listed() and "task_manager_tasks_list" in listed()


def test_the_guide_follows_both_switches(switches) -> None:
    off = instructions.guide(PANE, channel=True)
    assert "huddle" not in off.lower() and "swarm" in off
    switches.agent_huddle_tools = True
    on = instructions.guide(PANE, channel=True)
    assert "task_manager_guide" in on and on.startswith("CHANNEL EVENTS")
    switches.agent_swarm_tools = False
    assert "swarm" not in instructions.guide(PANE).lower()
    assert len(on) <= instructions.MAX_CHARS


def test_a_toggle_changes_the_fingerprint_so_connected_clients_refresh(switches) -> None:
    before = protocol.tool_fingerprint(PANE)
    switches.agent_huddle_tools = True
    after = protocol.tool_fingerprint(PANE)
    assert before != after
    switches.agent_huddle_tools = False
    assert protocol.tool_fingerprint(PANE) == before


def test_the_route_reads_and_writes_through_the_config_writer_and_needs_the_owner(env, monkeypatch, tmp_path) -> None:  # noqa: F811
    from src.api import mcp_admin_routes
    from src.api.auth import require_auth
    from src.core import config_writer
    from src.main import app

    client, mgr, _cfg = env
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"mcp": {"channels": true}}')
    monkeypatch.setattr(mcp_admin_routes, "settings", SimpleNamespace(
        auth_config_file=str(cfg_file), drop_auth_config_cache=lambda: None, port=8123,
        load_auth_config=lambda: SimpleNamespace(mcp=McpConfig())))
    monkeypatch.setattr(agent_tool_switches, "settings", SimpleNamespace(
        load_auth_config=lambda: SimpleNamespace(mcp=McpConfig(**json.loads(cfg_file.read_text())["mcp"]))))
    commits: list = []
    real_commit = config_writer.commit
    monkeypatch.setattr(config_writer, "commit", lambda path, mutate: commits.append(path) or real_commit(path, mutate))
    passes: list = []

    async def fake_pass(app_) -> None:
        passes.append(app_)

    monkeypatch.setattr(mcp_admin_routes, "run_required_pass", fake_pass)
    assert client.get("/api/v1/mcp-admin/agent-tools", headers=_hdr(mgr)).status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        assert client.get("/api/v1/mcp-admin/agent-tools").json() == {"huddle": False, "swarm": True, "app_settings": False}
        r = client.put("/api/v1/mcp-admin/agent-tools", json={"huddle": True})
        assert r.status_code == 200 and r.json() == {"huddle": True, "swarm": True, "app_settings": False}
        assert len(passes) == 1
        r = client.put("/api/v1/mcp-admin/agent-tools", json={"swarm": False})
        assert r.json() == {"huddle": True, "swarm": False, "app_settings": False} and len(passes) == 1
        r = client.put("/api/v1/mcp-admin/agent-tools", json={"app_settings": True})
        assert r.json() == {"huddle": True, "swarm": False, "app_settings": True} and len(passes) == 1
        assert client.put("/api/v1/mcp-admin/agent-tools", json={}).status_code == 422
        status = client.get("/api/v1/mcp-admin").json()
        assert (status["agent_huddle_tools"], status["agent_swarm_tools"], status["agent_app_settings_tools"]) == (True, False, True)
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert json.loads(cfg_file.read_text())["mcp"] == {"channels": True, "agent_huddle_tools": True, "agent_swarm_tools": False,
                                                       "agent_app_settings_tools": True}
    assert len(commits) == 3
