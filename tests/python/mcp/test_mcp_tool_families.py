
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from src.config import settings
from src.config.mcp import McpConfig
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.flow_data import mcp_events
from src.core.mcp import agent_tool_switches, aliases, family_signals, protocol, read_only_hint, tool_families, tools
from src.core.mcp.caller import AgentCaller

pytestmark = [pytest.mark.real_agent_tool_switches, pytest.mark.real_tool_family_signals]

PANE = AgentCaller(session_id="ses_a", tmux_name="carnivore_a", current_session_id="ses_a")
READ_TOKEN = AgentCaller(session_id="mcp-token:t", tmux_name="mcp-token:t", current_session_id="mcp-token:t", token_name="t", scope="read")
WRITE_TOKEN = AgentCaller(session_id="mcp-token:w", tmux_name="mcp-token:w", current_session_id="mcp-token:w", token_name="w", scope="write")

PACK_TOOL, PACK_ONRAMP = "pack_op_get", "computer_add"
MESSAGING_TOOL = "messaging_send"
AI_TOOL, AI_ONRAMP = "ai_models_list", "ai_connections_list"


@pytest.fixture
def cfg(monkeypatch) -> McpConfig:
    block = McpConfig()
    monkeypatch.setattr(agent_tool_switches, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=block)))
    return block


@pytest.fixture
def world(tmp_path, monkeypatch, cfg):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    monkeypatch.setattr(settings, "auth_config_file", str(config_file), raising=False)
    family_signals.invalidate()
    yield SimpleNamespace(state=state, config_file=config_file,
                          db=lambda: closing(connect(db_path_for(state), create=False)))
    family_signals.invalidate()


def _names(caller=PANE) -> set:
    return {d["name"] for d in tools.tool_definitions(caller)}


def _pack_row(conn: sqlite3.Connection) -> None:
    from src.core.computers import store

    store.put(conn, store.LinkRow("peer-install-1", "member", "tls", ""))


def _project(conn: sqlite3.Connection, name: str = "trader") -> tuple[int, str]:
    from src.core.project_writes import create_project

    row = create_project(conn, name=name, path=f"/tmp/{name}-families-test")
    return row["id"], conn.execute("SELECT uid FROM projects WHERE id = ?", (row["id"],)).fetchone()[0]



def test_every_family_member_is_a_registered_tool_and_the_table_is_sane() -> None:
    registered = set(tools.tool_names())
    for family in tool_families.FAMILIES:
        assert hasattr(agent_tool_switches.AgentToolSwitches(huddle=True, swarm=True), family.key), family.key
        assert family.names <= registered, sorted(family.names - registered)
        assert any(family.has(n) for n in registered), family.key
    for name in registered:
        assert sum(f.has(name) for f in tool_families.FAMILIES) <= 1, name
    assert len(tool_families.BY_KEY["pack"].names) == 33 and len(tool_families.BY_KEY["messaging"].names) == 6
    assert len(tool_families.BY_KEY["ai"].names) == 3 and len(tool_families.BY_KEY["app_settings"].names) == 21
    joes = {"dashboards_list", "widgets_list", "item_settings_get", "item_settings_update", "dashboard_create", "dashboard_rename",
            "dashboard_layout_set", "dashboard_activate", "dashboard_delete", "widget_bars_reset", "board_export", "board_import"}
    assert not [n for n in joes if tool_families.family_of(n)]
    assert tool_families.family_of("themes_list") is None
    assert tool_families.family_of("task_manager_list").key == "huddle"



def test_an_ssh_paired_computer_shows_pack_and_unpairing_hides_it(world) -> None:
    from src.core.federation import peer_hosts

    assert PACK_TOOL not in _names()
    with world.db() as conn:
        peer_hosts.upsert(conn, install_id="peer-install-9", label="studio", grant_id="g", fid="f", initiator=True)
    assert PACK_TOOL in _names()
    with world.db() as conn:
        peer_hosts.delete(conn, "peer-install-9")
    assert PACK_TOOL not in _names()


def test_pack_tools_follow_the_stored_pack_records(world) -> None:
    from src.core.pack.identity import home, replicas
    from src.core.pack.migrate import ops
    from src.core.pack.placement import queue

    assert PACK_TOOL not in _names() and PACK_ONRAMP in _names() and "computers_list" in _names()
    with world.db() as conn:
        _pack_row(conn)
    assert PACK_TOOL in _names()
    with world.db() as conn:
        conn.execute("DELETE FROM computer_links")
        from src.core.computers import store
        store.refresh(conn)
    assert PACK_TOOL not in _names()
    with world.db() as conn:
        replicas.record_replica(conn, "uid-1", "peer-install-1", "/tmp/r", "git")
    assert PACK_TOOL in _names()
    with world.db() as conn:
        replicas.forget_replica(conn, "uid-1", "peer-install-1")
    assert PACK_TOOL not in _names()
    with world.db() as conn:
        queue_id = queue.enqueue(conn, {"args": {}}, "no room")
    assert PACK_TOOL in _names()
    with world.db() as conn:
        queue.cancel(conn, queue_id)
    assert PACK_TOOL not in _names()
    with world.db() as conn:
        project_id, uid = _project(conn)
        ops.create(conn, op_id="op1", kind="project", role="source", subject_uid=uid, source_install_id="a", target_install_id="b", state="applying")
    assert PACK_TOOL in _names()
    with world.db() as conn:
        ops.update(conn, "op1", "source", state="failed", error_code="clone_failed")
    assert PACK_TOOL not in _names()
    with world.db() as conn:
        ops.update(conn, "op1", "source", state="flipped")
    assert PACK_TOOL not in _names()
    with world.db() as conn:
        home.set_state(conn, project_id, home.MOVED_AWAY, moved_to_install_id="b")
    assert PACK_TOOL in _names()
    with world.db() as conn:
        home.set_state(conn, project_id, home.HOME)
    assert PACK_TOOL not in _names()


def test_a_dropped_link_changes_neither_the_tool_list_nor_the_fingerprint(world) -> None:
    from src.core.computers import store

    with world.db() as conn:
        _pack_row(conn)
        before = protocol.tool_fingerprint(PANE)
        store.CACHE.replace([])
        store.touch_link(conn, "peer-install-1")
    assert PACK_TOOL in _names()
    assert protocol.tool_fingerprint(PANE) == before


def test_messaging_tools_follow_a_stored_provider_and_a_cursor_update_never_flips_it(world, monkeypatch) -> None:
    from src.core.messaging import message_store, store

    assert MESSAGING_TOOL not in _names()
    how = tool_families.BY_KEY["messaging"].how
    assert "settings > notifications > messaging" in how and "messaging_providers_list" not in how
    store.create_provider(provider_id="p_1", name="relay", owner_label="Joe", allow_private=False, allow_plain_http=False, capabilities={})
    assert MESSAGING_TOOL in _names()
    seen: list = []
    real = family_signals.invalidate
    monkeypatch.setattr(family_signals, "invalidate", lambda key=None: seen.append(key) or real(key))
    message_store.advance_cursor("p_1", 9)
    assert seen == [] and MESSAGING_TOOL in _names()
    assert store.delete_provider("p_1") is True
    assert MESSAGING_TOOL not in _names()


def test_ai_tools_follow_a_saved_connection_through_the_store_listener(world) -> None:
    from src.core.byoai import store as byoai_store

    assert AI_TOOL not in _names() and AI_ONRAMP in _names()
    world.config_file.write_text(json.dumps({"byoai": {"connections": [{"id": "c1"}]}}))
    assert AI_TOOL not in _names()
    byoai_store._notify_listeners(2)
    assert AI_TOOL in _names()
    world.config_file.write_text(json.dumps({"byoai": {"connections": []}}))
    byoai_store._notify_listeners(3)
    assert AI_TOOL not in _names()


def test_a_missing_config_holds_no_ai_connection(world) -> None:
    world.config_file.unlink()
    family_signals.invalidate("ai")
    assert AI_TOOL not in _names()



def test_the_app_settings_box_hides_exactly_its_tools_and_joes_stay_visible(cfg) -> None:
    members = tool_families.BY_KEY["app_settings"].names
    off = _names()
    assert not members & off
    assert {"dashboards_list", "widgets_list", "board_export", "themes_list", "session_theme_set"} <= off
    cfg.agent_app_settings_tools = True
    assert members <= _names()


def test_the_family_gates_bind_mcp_callers_only(cfg) -> None:
    everything = _names(None)
    assert tool_families.BY_KEY["app_settings"].names <= everything and tool_families.BY_KEY["pack"].names <= everything



@pytest.mark.parametrize("caller", [PANE, READ_TOKEN, WRITE_TOKEN])
def test_a_stale_call_to_a_hidden_tool_gets_the_named_refusal_not_the_read_only_one(world, monkeypatch, caller) -> None:
    denied: list = []
    real = mcp_events.mark_gate_denied
    monkeypatch.setattr(mcp_events, "mark_gate_denied", lambda: denied.append(True) or real())
    for name in ("pack_master_set", PACK_TOOL, MESSAGING_TOOL, AI_TOOL):
        result = asyncio.run(tools.call_tool(None, caller, name, {}))
        text = result["content"][0]["text"]
        assert result["isError"] is True and f"{name} is hidden:" in text and "read-only" not in text, (name, text)
    assert len(denied) == 4
    pack_text = asyncio.run(tools.call_tool(None, caller, PACK_TOOL, {}))["content"][0]["text"]
    assert "computer_add" in pack_text and "unlock after the join completes" in pack_text and "/mcp reconnect" in pack_text


def test_huddle_and_swarm_keep_their_refusal_words(cfg) -> None:
    huddle = asyncio.run(tools.call_tool(None, PANE, "huddle_list", {}))["content"][0]["text"]
    assert huddle == ("huddle_list is off: the owner turned huddle tools off for agents on this computer "
                      "(settings > sessions & agents > mcp server). Do not retry; tell the owner in your reply instead.")
    cfg.agent_swarm_tools = False
    swarm = asyncio.run(tools.call_tool(None, PANE, "swarm_roster", {}))["content"][0]["text"]
    assert swarm.endswith("(settings > sessions & agents > mcp server). Do not retry.") and swarm.startswith("swarm_roster is off:")



def test_listing_does_no_database_query_after_the_first_read(world, monkeypatch) -> None:
    asked: list = []
    real = family_signals._ask
    monkeypatch.setattr(family_signals, "_ask", lambda sql: asked.append(sql) or real(sql))
    for _ in range(30):
        tools.tool_definitions(PANE)
        protocol.tool_fingerprint(PANE)
    assert len(asked) == 2


def test_a_read_error_shows_the_family_and_is_logged_once(world, monkeypatch) -> None:
    calls: list = []

    def broken(sql: str) -> bool:
        calls.append(sql)
        raise sqlite3.OperationalError("no such table")

    logged: list = []
    monkeypatch.setattr(family_signals, "_ask", broken)
    monkeypatch.setattr(family_signals.logger, "warning", lambda event, **kw: logged.append((event, kw)))
    for _ in range(5):
        names = _names()
    assert PACK_TOOL in names and MESSAGING_TOOL in names
    assert len(calls) == 2 and len(logged) == 2 and {kw["family"] for _e, kw in logged} == {"pack", "messaging"}


def test_an_invalidate_during_a_probe_is_not_overwritten_by_it(monkeypatch) -> None:
    state = {"value": False}
    signal = family_signals._Signal("pack", lambda: state["value"])

    def racing_probe() -> bool:
        stale = state["value"]
        signal.invalidate()
        return stale

    signal._probe = racing_probe
    assert signal.read() is False
    state["value"] = True
    signal._probe = lambda: state["value"]
    assert signal.read() is True



def test_whoami_lists_the_hidden_families_with_why_and_how(world, cfg) -> None:
    result = asyncio.run(tools.call_tool(None, WRITE_TOKEN, "whoami", {}))
    body = json.loads(result["content"][0]["text"])
    rows = {r["family"]: r for r in body["hidden_families"]}
    assert set(rows) == {"huddle tools", "pack tools", "messaging tools", "ai tools", "app settings tools"}
    assert all(r["why"] and r["how_to_enable"] for r in rows.values())
    assert "computer_add" in rows["pack tools"]["how_to_enable"]
    cfg.agent_huddle_tools = cfg.agent_app_settings_tools = True
    with world.db() as conn:
        _pack_row(conn)
    family_signals.invalidate()
    again = json.loads(asyncio.run(tools.call_tool(None, WRITE_TOKEN, "whoami", {}))["content"][0]["text"])
    assert {r["family"] for r in again["hidden_families"]} == {"messaging tools", "ai tools"}


def test_add_and_invite_results_say_when_the_pack_tools_unlock(world) -> None:
    from src.core.mcp import computers_tools as ct

    async def route(*_a):
        return {"job_id": "j1", "id": "i1", "expires_at": "x"}

    call = SimpleNamespace(route=route, request=None, args={"ssh_target": "alex@studio", "host_key_sha256": "SHA256:" + "A" * 43})
    invited = asyncio.run(ct._invite(call))
    assert invited["note"] == ct.UNLOCK_NOTE and "after the join completes" in ct.UNLOCK_NOTE.lower() and "/mcp reconnect" in ct.UNLOCK_NOTE
    added = asyncio.run(ct._add(call))
    assert added["job_id"] == "j1" and added["note"] == ct.UNLOCK_NOTE
    with world.db() as conn:
        _pack_row(conn)
    assert "note" not in asyncio.run(ct._invite(call)) and "note" not in asyncio.run(ct._add(call))



def test_read_tools_carry_the_hint_and_the_excluded_ones_and_every_write_tool_do_not(world, cfg) -> None:
    cfg.agent_huddle_tools = cfg.agent_app_settings_tools = True
    listed = {d["name"]: d for d in tools.tool_definitions(WRITE_TOKEN)}
    assert listed["sessions_list"]["annotations"] == {"readOnlyHint": True}
    for name in ("crosstalk_inbox", "crosstalk_wait", "crosstalk_thread", "perf_profile", "task_manager_changes", "huddle_changes", "session_send_keys"):
        assert "annotations" not in listed[name], name
    assert not [n for n, d in listed.items() if "annotations" in d and n in tools.WRITE_TOOLS]
    registered_reads = set(tools.tool_names()) - tools.WRITE_TOOLS
    assert set(read_only_hint.NOT_READ_ONLY) <= registered_reads
    assert all(read_only_hint.NOT_READ_ONLY.values())
    expected = {n for n in registered_reads if aliases.canonical(n) not in read_only_hint.NOT_READ_ONLY}
    assert {n for n, d in listed.items() if "annotations" in d} == expected & set(listed)
