
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import mcp_health_listing
from src.core.conversation_writers import Proc, ProcessTable
from src.core.mcp_health.client_log import ClientLogReader
from src.core.mcp_health.monitor import McpMonitor, Target, measure_target
from src.cplugs.host import mcp_health_port
from src.cplugs.host.mcp_health_port import HostMcpHealth, health_from_document
from src.cplugs.runtime import guards
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens
from src.cplugs.sdk import ports
from src.cplugs.sdk.mcp_health import PORT_NAME
from src.models import Session, SessionInfo

SECRETS = ("SECRET_ARGV_9f3a", "SECRET_ENV_71bc", "SECRET_URL_c0de", "SECRET_QUERY_55aa", "SECRET_HEADER_42ee", "SECRET_AGENT_1d2c")
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _seed(tmp_path: Path):
    work = tmp_path / "proj"
    work.mkdir()
    config = {"mcpServers": {
        "memory": {"command": "/opt/bin/npx", "args": ["-y", "pkg-memory", f"--token={SECRETS[0]}"], "env": {"API_KEY": SECRETS[1]}},
        "remote": {"type": "http", "url": f"https://user:{SECRETS[2]}@example.com/mcp?key={SECRETS[3]}",
                   "headers": {"Authorization": f"Bearer {SECRETS[4]}"}},
    }}
    raw = json.dumps(config)
    cfg = tmp_path / "mcp.json"
    cfg.write_text(raw)
    table = ProcessTable.from_rows([
        Proc(100, 1, "Thu Oct 22 11:00:00 2026", "-zsh"),
        Proc(200, 100, "Thu Oct 22 11:00:01 2026", f"claude --mcp-config {cfg} --token {SECRETS[5]}"),
        Proc(300, 200, "Thu Oct 22 11:00:02 2026", f"npm exec pkg-memory --token={SECRETS[0]}"),
        Proc(400, 300, "Thu Oct 22 11:00:03 2026", f"/usr/local/bin/node /x/mcp-pkg-memory --token={SECRETS[0]}"),
    ])
    target = Target(session_id="ses_1", tmux_name="t1", family="claude", pane_pid=100, working_dir=str(work), agent_cwd=str(work))
    measure = measure_target(target, table, str(tmp_path / "claude-cfg"), NOW, ClientLogReader())
    raw += json.dumps({k: v.command for k, v in table.rows.items()})
    return raw, table, target, measure


def _port(monkeypatch, table, target, measure) -> HostMcpHealth:
    port = HostMcpHealth(deliver=None, render=None)
    port.monitor = McpMonitor()
    port.monitor._measures = {target.session_id: measure}
    port._targets = {target.session_id: target}
    monkeypatch.setattr(mcp_health_port, "read_process_table", lambda: table)
    return port


def _dispatcher(port: HostMcpHealth) -> HostDispatcher:
    return HostDispatcher(HostServices(activity=lambda e: None, process_snapshot=port.process_snapshot, mcp_config=port.mcp_config,
                                       mcp_links=port.mcp_links), OwnerTokens())


def _ctx(tmp_path: Path, granted=("mcp.health.read",)) -> PluginContext:
    return PluginContext(plugin_id="mcphealth", install_key="k", data_dir=tmp_path / "data", granted=frozenset(granted))


def test_the_methods_answer_names_and_states_and_never_a_secret(tmp_path, monkeypatch):
    raw, table, target, measure = _seed(tmp_path)
    assert all(s in raw for s in SECRETS)
    assert measure is not None and {s.name for s in measure.specs} >= {"memory", "remote"}
    dispatcher, ctx = _dispatcher(_port(monkeypatch, table, target, measure)), _ctx(tmp_path)

    async def call_all():
        return [await dispatcher.handle(ctx, m, {}) for m in ("process.snapshot", "mcp.config", "mcp.links")]

    snapshot, config, links = asyncio.run(call_all())
    answer = json.dumps([snapshot, config, links])
    assert not [s for s in SECRETS if s in answer], "a secret reached the plugin"
    assert {p["name"] for p in snapshot["processes"]} == {"claude", "npm", "node"}
    servers = {s["name"]: s for s in config["sessions"][0]["servers"]}
    assert servers["memory"]["command"] == "npx" and servers["memory"]["transport"] == "stdio"
    assert servers["remote"]["transport"] == "http" and servers["remote"]["command"] is None
    assert set(servers["memory"]) == {"name", "transport", "scope", "command", "alive"}
    assert links["sessions"][0]["session"] == "ses_1"


def test_a_plugin_without_the_grant_is_refused_and_a_session_filter_narrows(tmp_path, monkeypatch):
    _raw, table, target, measure = _seed(tmp_path)
    dispatcher = _dispatcher(_port(monkeypatch, table, target, measure))
    for method in ("process.snapshot", "mcp.config", "mcp.links"):
        with pytest.raises(guards.Refused) as err:
            asyncio.run(dispatcher.handle(_ctx(tmp_path, granted=("sessions.read",)), method, {}))
        assert err.value.code == "not_granted" and err.value.data == {"permission": "mcp.health.read"}
    other = asyncio.run(dispatcher.handle(_ctx(tmp_path), "mcp.config", {"session": "ses_nope"}))
    assert other == {"sessions": []}
    with pytest.raises(guards.Refused) as bad:
        asyncio.run(dispatcher.handle(_ctx(tmp_path), "mcp.config", {"session": 7}))
    assert bad.value.code == "invalid_params"


def test_with_the_sidecar_off_the_port_is_absent_and_rows_read_null(tmp_path):
    ports.unregister(PORT_NAME)
    row = SessionInfo(session=Session(id="ses_1", working_dir=str(tmp_path), tmux_session="t1"), tmux_session="t1",
                      activity_status="idle", agent_family="claude")
    mcp_health_listing.mark_mcp_health(SimpleNamespace(), [row])
    assert ports.get(PORT_NAME) is None and row.mcp_health is None


def test_the_port_answers_from_the_cached_document_and_stop_withdraws_it(tmp_path, monkeypatch):
    _raw, table, target, measure = _seed(tmp_path)
    document = {"data": {"sessions": {"ses_1": {"servers": [
        {"name": "memory", "transport": "stdio", "state": "down", "reason": "process_gone", "source": "process"}],
        "dropped": [{"name": "memory", "state": "dropped", "source": "bogus"}]}}}}

    async def scenario():
        port = HostMcpHealth(deliver=None, render=lambda: asyncio.sleep(0, document))
        port.start()
        assert ports.get(PORT_NAME) is port
        await port.refresh()
        row = SessionInfo(session=Session(id="ses_1", working_dir=str(tmp_path), tmux_session="t1"), tmux_session="t1",
                          activity_status="idle", agent_family="claude")
        health = port.health_for(None, row, NOW)
        await port.stop()
        return health, ports.get(PORT_NAME), port.health_for(None, row, NOW)

    health, after_port, after_health = asyncio.run(scenario())
    assert health.servers[0].state == "down" and health.servers[0].reason == "process_gone"
    assert health.dropped[0].source == "transcript"
    assert after_port is None and after_health is None
    assert health_from_document({"data": {"sessions": {}}}, "ses_1") is None


def test_a_burst_of_changes_is_one_event_then_one_more(tmp_path):
    sent = []

    async def deliver(family, seq, payload):
        sent.append((family, seq))
        await asyncio.sleep(0.01)
        return True

    async def scenario():
        port = HostMcpHealth(deliver=deliver, render=None)
        port._moved()
        port._moved()
        await asyncio.sleep(0.001)
        for _ in range(4):
            port._moved()
        await port._wake_task

    asyncio.run(scenario())
    assert sent == [("mcp.health", 1), ("mcp.health", 2)]
