
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import beast_mode_routes
from src.core.approvals import beast_policy
from src.core.mcp import beast_mode, beast_store, tools
from src.cplugs.host import runtime


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mcp": {"enabled": True, "beast_mode": False}, "unrelated": 1}))
    monkeypatch.setattr(beast_mode_routes.settings, "auth_config_file", str(path))
    monkeypatch.setattr(beast_store.resource_push, "notify", lambda topic: None)
    beast_mode_routes.settings.drop_auth_config_cache()
    return path


def test_there_is_no_beast_mode_plugin_and_arming_never_asks_for_one(config: Path) -> None:
    assert runtime.find("beastmode") is None
    assert not hasattr(beast_mode, "plugin_on") and not hasattr(beast_mode, "policy")
    assert "available" not in asyncio.run(beast_mode_routes.get_beast_mode())
    result = asyncio.run(beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=True, prompts=True)))
    assert result["enabled"] is True and result["prompts"] is True
    assert json.loads(config.read_text())["mcp"]["beast_mode"] is True


def test_the_default_grid_answers_as_it_did_as_a_plugin(config: Path) -> None:
    policy = beast_policy.current()
    assert all(policy.handles(r) for r in ("dev_channels", "folder_trust", "external_imports", "chrome_decline")), "startup rows, disarmed"
    assert not any(policy.handles(r) for r in ("claude_permission", "codex_approval", "agent_writes")), "disarmed: nothing else"
    assert beast_mode.approval_skip("session_wake") is False
    asyncio.run(beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=True)))
    assert beast_mode.approval_skip("session_wake") is True and beast_mode.beast_enabled()
    assert policy.handles("claude_permission") is False, "armed without the prompts scope never pressed a prompt"
    asyncio.run(beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=True, prompts=True)))
    assert policy.handles("claude_permission") is True and policy.handles("codex_approval") is True
    assert policy.trust_scope() == "projects"


def test_the_rules_route_edits_the_grid_and_leaves_the_switch_alone(config: Path) -> None:
    asyncio.run(beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=True)))
    body = beast_mode_routes.BeastGridUpdate(cells={"agentWritesOn": False, "folderTrustOff": False}, trust_scope="every")
    answer = asyncio.run(beast_mode_routes.put_beast_rules(body))
    written = json.loads(config.read_text())
    assert written["mcp"]["beast_grid"] == {"agentWritesOn": False, "folderTrustOff": False} and written["mcp"]["beast_trust_scope"] == "every"
    assert written["mcp"]["beast_mode"] is True and written["unrelated"] == 1
    assert answer["trust_scope"] == "every" and answer["cells"]["agentWritesOn"] == {"value": False, "default": True}
    assert answer["cells"]["folderTrustOn"] == {"value": True, "default": True}
    assert {r["id"]: r for r in answer["rows"]}["agent_writes"]["handled_now"] is False
    assert beast_mode.approval_skip("session_wake") is False, "the unticked beast on box takes effect on the next decision"
    again = asyncio.run(beast_mode_routes.put_beast_rules(beast_mode_routes.BeastGridUpdate(cells={"agentWritesOn": True})))
    assert json.loads(config.read_text())["mcp"]["beast_grid"] == {"agentWritesOn": True, "folderTrustOff": False}, "boxes merge"
    assert again["trust_scope"] == "every", "an absent scope is left alone"


@pytest.mark.parametrize("cells", [{"nope": True}, {"agentWritesOn": "yes"}, {"agentWritesOn": 1}])
def test_the_rules_route_refuses_what_is_no_box(config: Path, cells: dict) -> None:
    before = config.read_text()
    with pytest.raises((HTTPException, ValueError)) as caught:
        asyncio.run(beast_mode_routes.put_beast_rules(beast_mode_routes.BeastGridUpdate.model_construct(cells=cells, trust_scope=None)))
    assert getattr(caught.value, "status_code", 422) == 422 and config.read_text() == before


def test_the_grid_body_refuses_extra_keys_and_an_unknown_scope() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        beast_mode_routes.BeastGridUpdate(trust_scope="elsewhere")
    with pytest.raises(ValidationError):
        beast_mode_routes.BeastGridUpdate(enabled=True)


def test_the_two_tools_are_core_tools_that_can_only_read_and_disarm(config: Path) -> None:
    assert set(n for n in tools._TOOLS if n.startswith("beastmode")) == {"beastmode_status", "beastmode_off"}
    assert "beastmode_off" in tools.WRITE_TOOLS and "beastmode_status" not in tools.WRITE_TOOLS
    for row in tools.tool_definitions(None):
        if row["name"].startswith("beastmode"):
            assert row["inputSchema"]["properties"] == {}, row["name"]
    manager = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    from src.core.mcp import beast_tools
    from src.core.mcp.caller import AgentCaller
    from src.core.mcp.common import ToolError

    caller = AgentCaller("ses_a", "cloude_a", "ses_a")
    asyncio.run(beast_mode_routes.put_beast_mode(beast_mode_routes.BeastSetting(enabled=True)))
    with pytest.raises(ToolError, match="only turn Beast Mode off"):
        asyncio.run(beast_tools.beastmode_off(manager, caller, {"enabled": True}))
    assert json.loads(config.read_text())["mcp"]["beast_mode"] is True
    asyncio.run(beast_tools.beastmode_off(manager, caller, {}))
    assert json.loads(config.read_text())["mcp"]["beast_mode"] is False


def test_the_status_tool_carries_the_switch_and_the_grid(config: Path) -> None:
    from src.core.mcp import beast_tools

    spec = beast_tools.SPECS[0]
    call = SimpleNamespace(route=beast_mode_routes.get_beast_mode)
    answer = asyncio.run(spec.invoke(call))
    assert answer["enabled"] is False and answer["grid"]["rows"][0]["id"] == "dev_channels" and answer["grid"]["trust_scope"] == "projects"
