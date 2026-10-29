
from datetime import datetime, timezone

import pytest

from src.core.conversation_writers import Proc, ProcessTable
from src.core.mcp_health import cached_files
from src.core.mcp_health import config_codex, monitor as monitor_mod
from src.core.mcp_health.client_log import ClientLogReader, cwd_slug, log_dir_name
from src.core.mcp_health.agent_process import lstart_to_datetime
from src.core.mcp_health.monitor import McpMonitor, Target, measure_target

NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
LSTART = "Mon Oct 12 11:00:00 2026"


@pytest.fixture(autouse=True)
def _no_real_codex_home(tmp_path, monkeypatch):
    monkeypatch.setattr(config_codex, "DEFAULT_CODEX_HOME", str(tmp_path / "no-default-codex-home"))


def _table():
    return ProcessTable.from_rows([
        Proc(10, 1, LSTART, "-zsh"),
        Proc(11, 10, LSTART, "node /opt/homebrew/bin/codex -c mcp_servers.files.command=\"npx\" "
                             "-c mcp_servers.files.args=[\"@mcp/files\"]"),
        Proc(12, 11, LSTART, "/opt/homebrew/lib/node_modules/@openai/codex/vendor/codex/codex"),
        Proc(13, 12, LSTART, "npm exec @mcp/files"),
        Proc(20, 1, LSTART, "-zsh"),
        Proc(21, 20, LSTART, "claude --strict-mcp-config --mcp-config={\"mcpServers\":{\"m\":{\"command\":\"npx\","
                             "\"args\":[\"-y\",\"pkg-m\"]}}}"),
    ])


def test_codex_agent_under_its_pane_and_its_stdio_child(tmp_path):
    cached_files.reset()
    target = Target("ses_x", "carnivore_x", "codex", pane_pid=10, working_dir=str(tmp_path))
    got = measure_target(target, _table(), str(tmp_path / "no-codex-home"), NOW, ClientLogReader(root=str(tmp_path)))
    assert [s.name for s in got.specs] == ["files"] and got.alive == {"files": True}
    assert got.links is None and got.agent_started_at == lstart_to_datetime(LSTART)


def test_claude_by_registry_pid_and_a_missing_stdio_server(tmp_path):
    started = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
    target = Target("ses_c", "carnivore_c", "claude", pane_pid=20, agent_pid=21, agent_started_at=started,
                    agent_cwd=str(tmp_path))
    got = measure_target(target, _table(), None, NOW, ClientLogReader(root=str(tmp_path)))
    assert [s.name for s in got.specs] == ["m"] and got.alive == {"m": False}
    assert got.agent_started_at == started and got.links is None


def test_one_cycle_takes_one_ps_table_and_reports_a_change(tmp_path, monkeypatch):
    calls = []

    def table(max_age=0.0):
        calls.append(1)
        return _table()

    monkeypatch.setattr(monitor_mod, "read_process_table", table)
    mon = McpMonitor(reader=ClientLogReader(root=str(tmp_path)))
    try:
        targets = [Target("ses_x", "carnivore_x", "codex", pane_pid=10), Target("ses_c", "carnivore_c", "claude",
                                                                             pane_pid=20)]
        mon.register(targets)
        assert mon._cycle_sync(targets, {}) is True and len(calls) == 1
        assert mon.measure_for("ses_x").alive == {"files": True}
        assert mon._cycle_sync(targets, {}) is False
    finally:
        mon.close()


def test_the_run_loop_measures_off_the_loop_and_wakes_the_listing(tmp_path, monkeypatch):
    import asyncio

    from src.core.account_switch.pane_account import PaneProfile

    async def profile(socket, name, variable):
        return PaneProfile(readable=True, value=None)

    monkeypatch.setattr(monitor_mod, "read_process_table", lambda max_age=0.0: _table())
    monkeypatch.setattr(monitor_mod, "read_pane_profile", profile)
    mon = McpMonitor(reader=ClientLogReader(root=str(tmp_path)), cycle=0.01)
    mon.register([Target("ses_x", "carnivore_x", "codex", pane_pid=10)])

    async def drive():
        woke = asyncio.Event()
        task = asyncio.create_task(mon.run(lambda: "throwaway-socket", woke.set))
        try:
            await asyncio.wait_for(woke.wait(), 5)
        finally:
            task.cancel()
        return mon.measure_for("ses_x")

    try:
        assert asyncio.run(drive()).alive == {"files": True}
    finally:
        mon.close()


def test_a_server_added_to_the_user_config_after_claude_started_is_not_down(tmp_path):
    import json as _json

    started = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
    cwd = tmp_path / "proj"
    cwd.mkdir()
    config_dir = tmp_path / "profile"
    config_dir.mkdir()
    (config_dir / ".claude.json").write_text(_json.dumps({"mcpServers": {
        "memory": {"command": "npx", "args": ["-y", "pkg-memory"]},
        "late": {"command": "/venv/bin/python", "args": ["/srv/late_server.py"]},
    }}))
    shared = tmp_path / "carnivore-mcp.json"
    shared.write_text(_json.dumps({"mcpServers": {"later": {"command": "/venv/bin/python", "args": ["/srv/later.py"]}}}))
    logs = tmp_path / "cache"
    stamp = started.strftime("%Y-%m-%dT%H-%M-%S-") + "250Z.jsonl"
    line = _json.dumps({"debug": "Successfully connected (transport: stdio)", "timestamp": "2026-10-12T15:00:01.000Z"})
    for server in ("m", "memory"):
        folder = logs / cwd_slug(str(cwd)) / log_dir_name(server)
        folder.mkdir(parents=True)
        (folder / stamp).write_text(line + "\n")
    table = ProcessTable.from_rows([
        Proc(20, 1, LSTART, "-zsh"),
        Proc(21, 20, LSTART, "claude --mcp-config={\"mcpServers\":{\"m\":{\"command\":\"npx\",\"args\":[\"-y\",\"pkg-m\"]}}}"
                             f" --mcp-config={shared}"),
        Proc(22, 21, LSTART, "npm exec pkg-m"),
        Proc(23, 21, LSTART, "npm exec pkg-memory"),
    ])
    cached_files.reset()
    target = Target("ses_c", "carnivore_c", "claude", pane_pid=20, agent_pid=21, agent_started_at=started,
                    agent_cwd=str(cwd))
    got = measure_target(target, table, str(config_dir), NOW, ClientLogReader(root=str(logs)))
    assert got.links is not None and set(got.links) == {"m", "memory"}
    assert {"late", "later"} <= got.excluded and [s.key for s in got.specs] == ["m", "memory"]
    assert got.alive.get("m") is True and got.alive.get("memory") is True


def test_a_file_scoped_server_is_still_judged_when_the_log_cannot_speak_for_the_process(tmp_path):
    import json as _json

    started = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
    config_dir = tmp_path / "profile"
    config_dir.mkdir()
    (config_dir / ".claude.json").write_text(_json.dumps({"mcpServers": {
        "late": {"command": "/venv/bin/python", "args": ["/srv/late_server.py"]}}}))
    cached_files.reset()
    target = Target("ses_c", "carnivore_c", "claude", pane_pid=20, agent_pid=21, agent_started_at=started,
                    agent_cwd=str(tmp_path))
    table = ProcessTable.from_rows([Proc(20, 1, LSTART, "-zsh"), Proc(21, 20, LSTART, "claude")])
    got = measure_target(target, table, str(config_dir), NOW, ClientLogReader(root=str(tmp_path / "cache")))
    assert "late" in [s.key for s in got.specs] and got.alive.get("late") is False
