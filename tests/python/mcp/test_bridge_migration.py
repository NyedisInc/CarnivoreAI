
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_bm_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_bm_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.config import mcp_launch  # noqa: E402
from src.core.conversation_writers import MeasureError, Proc, ProcessTable  # noqa: E402
from src.core.mcp_bridge.migration import detect, idle, migrator as mig  # noqa: E402
from src.core.session_respawn import (  # noqa: E402
    LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION, RESPAWN_CANNOT_DETERMINE, resolve_respawn_plan)

HTTP_ARGV = "claude " + mcp_launch.CLAUDE_MCP_CONFIG_FLAG + "=" + json.dumps(
    {"mcpServers": {"carnivore": mcp_launch._http_server_doc(False)}}, separators=(",", ":"))
STDIO_ARGV = "claude " + mcp_launch.claude_args(bridge_script=mcp_launch.BRIDGE_SCRIPT)[0]


def _quiet_evidence() -> SimpleNamespace:
    return SimpleNamespace(
        agent_family="claude", timers=SimpleNamespace(state="ok", live=0),
        subagents=SimpleNamespace(state="ok", running=0),
        background_process=SimpleNamespace(state="none", count=0), background_open=0, parked_work=None,
        registry=SimpleNamespace(known=True, pid=None))


def _info(name: str, pane_pid: int, **over: Any) -> SimpleNamespace:
    base = dict(agent_family="claude", tmux_session=name, activity_status="idle", startup_gate="ready",
                activity_hint=None, subagents_running=0, background_open=0, host_key="local",
                session=SimpleNamespace(id=f"ses_{name}", pty_pid=pane_pid))
    base.update(over)
    return SimpleNamespace(**base)


def _table(rows: Dict[int, str]) -> ProcessTable:
    procs = []
    for pane, command in rows.items():
        procs.append(Proc(pane, 1, "Mon Oct 12 12:00:00 2026", "-zsh"))
        procs.append(Proc(pane + 1, pane, "Mon Oct 12 12:00:00 2026", command))
    return ProcessTable.from_rows(procs)



def test_detector_reads_http_stdio_and_none() -> None:
    assert detect.carnivore_transport(HTTP_ARGV) == "http"
    assert detect.carnivore_transport(STDIO_ARGV) == "stdio"
    assert detect.carnivore_transport("claude --model opus") == detect.TRANSPORT_NONE
    other = "claude --mcp-config=" + json.dumps({"mcpServers": {"memory": {"type": "http", "url": "u"}}})
    assert detect.carnivore_transport(other) == detect.TRANSPORT_NONE
    assert detect.needs_bridge("http") and not detect.needs_bridge("stdio") and not detect.needs_bridge(None)


def test_detector_reads_a_config_file_value(tmp_path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"carnivore": {"type": "http", "url": "http://x/mcp"}}}))
    assert detect.carnivore_transport(f"claude --mcp-config {path} --model x") == "http"


def test_session_transport_finds_the_claude_under_the_pane() -> None:
    table = _table({100: HTTP_ARGV, 200: STDIO_ARGV})
    assert detect.session_transport(table, 100, None) == "http"
    assert detect.session_transport(table, 200, None) == "stdio"
    assert detect.session_transport(table, 200, 101) == "http"
    assert detect.session_transport(table, 999, None) is None



OBS = SimpleNamespace(stale=False, evidence=_quiet_evidence())


@pytest.mark.parametrize("status", ["working", "working_subagent", "question", "notice", "unknown", "dead"])
def test_every_busy_state_refuses(status: str) -> None:
    assert idle.refusal(_info("a", 100, activity_status=status), OBS, 900.0) == f"status_{status}"


@pytest.mark.parametrize("over,reason", [
    ({"startup_gate": "awaiting_startup_prompt"}, idle.REASON_STARTUP_GATE),
    ({"startup_gate": "unknown"}, idle.REASON_STARTUP_GATE),
    ({"activity_hint": "shell"}, idle.REASON_SHELL_RUNNING),
    ({"subagents_running": 1}, idle.REASON_LIVE_WORK),
    ({"background_open": 2}, idle.REASON_LIVE_WORK),
    ({"agent_family": "codex"}, idle.REASON_NOT_CLAUDE),
    ({"host_key": "peer-x"}, idle.REASON_REMOTE),
    ({"tmux_session": None}, idle.REASON_NO_TMUX_NAME),
])
def test_each_gate_alone_refuses(over: dict, reason: str) -> None:
    assert idle.refusal(_info("a", 100, **over), OBS, 900.0) == reason


def test_observation_live_work_and_quiet_window() -> None:
    info = _info("a", 100)
    assert idle.refusal(info, None, 900.0) == idle.REASON_NO_OBSERVATION
    assert idle.refusal(info, SimpleNamespace(stale=True, evidence=_quiet_evidence()), 900.0) == idle.REASON_NO_OBSERVATION
    timers = _quiet_evidence()
    timers.timers = SimpleNamespace(state="ok", live=1, next_fire_at=None)
    assert idle.refusal(info, SimpleNamespace(stale=False, evidence=timers), 900.0) == idle.REASON_LIVE_WORK
    unmeasured = _quiet_evidence()
    unmeasured.subagents = None
    assert idle.refusal(info, SimpleNamespace(stale=False, evidence=unmeasured), 900.0) == idle.REASON_LIVE_WORK
    assert idle.refusal(info, OBS, None) == idle.REASON_QUIET_UNMEASURED
    assert idle.refusal(info, OBS, idle.IDLE_SECONDS - 1) == idle.REASON_NOT_QUIET
    assert idle.refusal(info, OBS, idle.IDLE_SECONDS) is None
    assert idle.refusal(_info("a", 100, activity_status="finished_unread"), OBS, 900.0) is None



def test_named_reason_is_carried_and_an_unknown_one_refused() -> None:
    live = dict(probe_ok=True, pane_dead="0", pane_start_command='"cld"', agent_command="cld --resume u",
                live_restart_confirmed=True)
    plan = resolve_respawn_plan(**live, live_restart_reason=LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION)
    assert plan.kills_live_pane and plan.kill_reason == LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION
    refused = resolve_respawn_plan(**live, live_restart_reason="anything_else")
    assert refused.kind == RESPAWN_CANNOT_DETERMINE and not refused.kills_live_pane
    assert resolve_respawn_plan(**live).kill_reason is None
    unconfirmed = dict(live, live_restart_confirmed=False)
    assert not resolve_respawn_plan(**unconfirmed, live_restart_reason=LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION
                                    ).kills_live_pane



class FakeManager:

    def __init__(self, infos: List[SimpleNamespace], argv: Dict[int, str]) -> None:
        self.infos = {i.tmux_session: i for i in infos}
        self.argv = argv
        self.calls: List[Dict[str, Any]] = []
        self.respawn_ok = True
        self.outcome = {i.tmux_session: "resumed" for i in infos}
        self._attention_watcher = SimpleNamespace(observation_for=lambda _sid, now=None: OBS)

    async def list_session_infos(self) -> list:
        return list(self.infos.values())

    async def get_session_info(self, session_id: str) -> Optional[SimpleNamespace]:
        return next((i for i in self.infos.values() if i.session.id == session_id), None)

    def tmux_socket_name(self) -> str:
        return "test-socket"

    def _resume_target_for_tmux_name(self, name: str, socket: str) -> SimpleNamespace:
        return SimpleNamespace(outcome=self.outcome[name])

    async def respawn_session(self, name: str, **kwargs: Any) -> dict:
        self.calls.append({"name": name, **kwargs})
        if not self.respawn_ok:
            return {"ok": False, "kind": "not_dead", "conversation": "resumed"}
        self.argv[self.infos[name].session.pty_pid] = STDIO_ARGV
        return {"ok": True, "kind": "agent", "conversation": "resumed", "killed_live_pane": True,
                "identity_status": "unchanged"}


class Clock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _migrator(manager: FakeManager, clock: Optional[Clock] = None, **over: Any) -> mig.BridgeMigrator:
    async def quiet(_name: str) -> float:
        return 900.0
    kwargs = dict(enabled=lambda: True, bridge_ready=lambda: True,
                  process_table=lambda: _table(manager.argv), monotonic=clock or Clock(),
                  evidence=SimpleNamespace(quiet_seconds=quiet))
    kwargs.update(over)
    return mig.BridgeMigrator(manager, **kwargs)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_one_restart_per_pass_with_resume_and_the_narrow_reason() -> None:
    manager = FakeManager([_info("a", 100), _info("b", 200), _info("c", 300)], {100: HTTP_ARGV, 200: HTTP_ARGV,
                                                                                    300: STDIO_ARGV})
    m = _migrator(manager)
    status = _run(m.run_pass())
    assert [c["name"] for c in manager.calls] == ["a"]
    call = manager.calls[0]
    assert call["live_restart_confirmed"] is True and call["require_agent_resume"] is True
    assert call["live_restart_reason"] == LIVE_RESTART_REASON_MCP_BRIDGE_MIGRATION
    states = {s["tmux_session"]: (s["state"], s["reason"]) for s in status["sessions"]}
    assert states == {"a": ("restarted", None), "b": ("pending", mig.REASON_ONE_AT_A_TIME)}
    _run(m.run_pass())
    assert [c["name"] for c in manager.calls] == ["a", "b"]
    _run(m.run_pass())
    assert len(manager.calls) == 2 and m.remaining() == 0
    assert {e.state for e in m.entries.values()} == {mig.STATE_MIGRATED}


def test_a_busy_session_is_never_restarted_and_waits() -> None:
    manager = FakeManager([_info("a", 100, activity_status="working")], {100: HTTP_ARGV})
    m = _migrator(manager)
    _run(m.run_pass())
    assert manager.calls == [] and m.entries["a"].reason == "status_working" and m.remaining() == 1
    manager.infos["a"].activity_status = "idle"
    _run(m.run_pass())
    assert [c["name"] for c in manager.calls] == ["a"]


def test_no_conversation_is_skipped_never_restarted() -> None:
    manager = FakeManager([_info("a", 100)], {100: HTTP_ARGV})
    manager.outcome["a"] = "none_recorded"
    m = _migrator(manager)
    _run(m.run_pass())
    assert manager.calls == [] and m.entries["a"].state == mig.STATE_SKIPPED
    assert m.entries["a"].reason == mig.REASON_NO_CONVERSATION


def test_attempt_cap_and_backoff_never_loop() -> None:
    clock = Clock()
    manager = FakeManager([_info("a", 100)], {100: HTTP_ARGV})
    manager.respawn_ok = False
    m = _migrator(manager, clock)
    _run(m.run_pass())
    assert len(manager.calls) == 1 and m.entries["a"].last_outcome == "refused_not_dead"
    _run(m.run_pass())
    assert len(manager.calls) == 1 and m.entries["a"].reason == mig.REASON_BACKOFF
    clock.now += mig.BACKOFF_SECONDS
    _run(m.run_pass())
    assert len(manager.calls) == 2
    clock.now += mig.BACKOFF_SECONDS * 2 - 1
    _run(m.run_pass())
    assert len(manager.calls) == 2
    for _ in range(10):
        clock.now += mig.BACKOFF_SECONDS * 100
        _run(m.run_pass())
    assert len(manager.calls) == mig.MAX_ATTEMPTS
    assert m.entries["a"].state == mig.STATE_GAVE_UP and m.remaining() == 0


def test_recheck_before_the_kill_refuses_a_session_that_woke() -> None:
    manager = FakeManager([_info("a", 100)], {100: HTTP_ARGV})
    seen = {"n": 0}

    async def quiet(_name: str) -> float:
        seen["n"] += 1
        if seen["n"] > 1:
            manager.infos["a"].activity_status = "working"
        return 900.0
    m = _migrator(manager, evidence=SimpleNamespace(quiet_seconds=quiet))
    _run(m.run_pass())
    assert manager.calls == [] and m.entries["a"].reason == "recheck_status_working"
    assert m.entries["a"].attempts == 0


@pytest.mark.parametrize("over,expected", [
    ({"enabled": lambda: False}, mig.PASS_DISABLED),
    ({"bridge_ready": lambda: False}, mig.PASS_BRIDGE_MISSING),
])
def test_off_switch_and_missing_bridge_do_nothing(over: dict, expected: str) -> None:
    manager = FakeManager([_info("a", 100)], {100: HTTP_ARGV})
    status = _run(_migrator(manager, **over).run_pass())
    assert manager.calls == [] and status["last_pass"] == expected and status["sessions"] == []


def test_ps_failure_restarts_nothing() -> None:
    def broken() -> ProcessTable:
        raise MeasureError("ps did not run")
    manager = FakeManager([_info("a", 100)], {100: HTTP_ARGV})
    status = _run(_migrator(manager, process_table=broken).run_pass())
    assert manager.calls == [] and status["last_pass"] == mig.PASS_PS_FAILED


def test_no_http_sessions_means_nothing_happens_and_the_loop_ends(monkeypatch) -> None:
    monkeypatch.setattr(mig, "BOOT_SETTLE_SECONDS", 0.0)
    manager = FakeManager([_info("a", 100)], {100: STDIO_ARGV})
    m = _migrator(manager)
    _run(asyncio.wait_for(m.run(None), 5))
    assert manager.calls == [] and m.entries == {} and m.looping is False



def test_routes_report_run_and_switch_behind_the_owner_login(monkeypatch, tmp_path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import mcp_admin_routes
    from src.api.auth import require_auth
    from src.config.mcp import McpConfig

    app = FastAPI()
    app.include_router(mcp_admin_routes.router)
    client = TestClient(app)
    assert client.get("/mcp-admin/bridge-migration").status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    assert client.get("/mcp-admin/bridge-migration").status_code == 503
    manager = FakeManager([_info("a", 100)], {100: HTTP_ARGV})
    app.state.mcp_bridge_migrator = _migrator(manager)
    assert client.get("/mcp-admin/bridge-migration").json()["sessions"] == []
    ran = client.post("/mcp-admin/bridge-migration/run").json()
    assert ran["last_pass"] == mig.PASS_RAN and ran["sessions"][0]["state"] == mig.STATE_RESTARTED
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"mcp": {"channels": true}}')
    monkeypatch.setattr(mcp_admin_routes, "settings", SimpleNamespace(
        auth_config_file=str(cfg_file), drop_auth_config_cache=lambda: None))
    assert client.put("/mcp-admin/bridge-migration", json={"enabled": False}).json() == {"enabled": False}
    assert json.loads(cfg_file.read_text())["mcp"] == {"channels": True, "bridge_migration": False}
    assert McpConfig().bridge_migration is True
