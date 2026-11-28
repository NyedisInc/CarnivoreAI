
from __future__ import annotations

import pytest

from src.core.mcp import agent_tool_switches, fingerprint_memo, protocol, tools
from src.core.mcp.caller import AgentCaller
from src.plugins.host import registry_store

PANE = AgentCaller(session_id="ses_a", tmux_name="carnivore_a", current_session_id="ses_a")


@pytest.fixture
def world(monkeypatch):
    fingerprint_memo.clear()
    state = {"defs": [{"name": "one"}], "computes": 0, "now": 500.0}

    def definitions(caller):
        state["computes"] += 1
        return list(state["defs"])

    monkeypatch.setattr(tools, "tool_definitions", definitions)
    monkeypatch.setattr(protocol.instructions, "guide", lambda caller, channel=False: "guide")
    monkeypatch.setattr(fingerprint_memo.time, "monotonic", lambda: state["now"])
    yield state
    fingerprint_memo.clear()


def test_the_fingerprint_is_reused_until_the_bound_passes(world) -> None:
    first = protocol.tool_fingerprint(PANE)
    assert len(first) == protocol.FINGERPRINT_CHARS
    assert protocol.tool_fingerprint(PANE) == first and protocol.session_is_current(f"{first}.x", PANE)
    assert world["computes"] == 1
    world["defs"] = [{"name": "one"}, {"name": "two"}]
    assert protocol.tool_fingerprint(PANE) == first
    world["now"] += fingerprint_memo.TTL_S + 0.1
    assert protocol.tool_fingerprint(PANE) != first and world["computes"] == 2


def test_the_channel_flag_and_the_caller_key_apart(world) -> None:
    protocol.tool_fingerprint(PANE)
    protocol.tool_fingerprint(PANE, True)
    protocol.tool_fingerprint(AgentCaller(session_id="ses_b", tmux_name="carnivore_b", current_session_id="ses_b"))
    assert world["computes"] == 3


def test_a_registry_write_makes_an_old_session_id_stale_at_once(world, tmp_path) -> None:
    old = f"{protocol.tool_fingerprint(PANE)}.abc"
    assert protocol.session_is_current(old, PANE)
    world["defs"] = [{"name": "one"}, {"name": "plugin_tool"}]
    registry_store.write_registry(tmp_path / "plugins" / "registry.json", registry_store.new_document())
    assert not protocol.session_is_current(old, PANE)


def test_a_checkbox_toggle_is_seen_at_once(world, monkeypatch) -> None:
    flags = {"huddle": False}
    monkeypatch.setattr(agent_tool_switches, "current",
                        lambda: agent_tool_switches.AgentToolSwitches(huddle=flags["huddle"], swarm=True))
    first = protocol.tool_fingerprint(PANE)
    flags["huddle"] = True
    world["defs"] = [{"name": "task_manager_x"}]
    assert protocol.tool_fingerprint(PANE) != first


def test_a_clear_during_a_compute_keeps_the_stale_value_out_of_the_memo(world) -> None:
    seen: list[str] = []

    def compute() -> str:
        fingerprint_memo.clear()
        seen.append("old")
        return "old"

    assert fingerprint_memo.remembered("k", compute) == "old"
    assert fingerprint_memo.remembered("k", lambda: "new") == "new"


def test_a_tool_override_reaches_the_fingerprint_through_the_config_stamp(world, monkeypatch) -> None:
    from types import SimpleNamespace

    from src.config.mcp import McpConfig

    block = McpConfig()
    monkeypatch.setattr(agent_tool_switches, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=block)))
    first = protocol.tool_fingerprint(PANE)
    block.tool_overrides = {"sessions_list": False}
    world["defs"] = [{"name": "fewer"}]
    assert protocol.tool_fingerprint(PANE) != first


def test_a_registry_swap_clears_the_memo(world) -> None:
    from src.plugins.host import sidecar_registry

    first = protocol.tool_fingerprint(PANE)
    world["defs"] = [{"name": "one"}, {"name": "installed__ping"}]
    sidecar_registry.install(sidecar_registry.current())
    assert protocol.tool_fingerprint(PANE) != first
