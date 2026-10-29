
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mcp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mcp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import AgentsConfig, Settings, mcp_launch
from src.config.mcp import McpConfig
from src.config.session import SessionConfig
from src.core.mcp import channel, protocol
from src.core.session_agent_infer import PER_RUN_FLAGS
from tests.python.mcp.test_mcp_endpoint import _hdr, _rpc, env  # noqa: F401

FLAG = "--dangerously-load-development-channels=server:carnivore"
CHANNEL = {"X-Carnivore-Channel": "1"}


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path))
    s = Settings()
    monkeypatch.setattr(s, "port", 8123)

    def configure(enabled: bool = True, channels: bool = False) -> Settings:
        monkeypatch.setattr(Settings, "load_auth_config", lambda self: SimpleNamespace(
            agents=AgentsConfig(), session=SessionConfig(), mcp=McpConfig(enabled=enabled, channels=channels),
            launch_profiles=None, byoai=None))
        return s

    return configure


@pytest.fixture
def channels_on(monkeypatch):
    cfg = McpConfig(channels=True)
    monkeypatch.setattr(channel, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=cfg)))
    return cfg


@pytest.fixture
def registry(monkeypatch):
    fresh = channel.ChannelRegistry()
    monkeypatch.setattr(channel, "REGISTRY", fresh)
    monkeypatch.setattr(channel, "STREAM_MAX_S", 0.3)
    return fresh



def test_setting_off_adds_no_flag_and_no_header(launcher) -> None:
    cmd = launcher(channels=False).get_agent_command("claude", pane_launch=True)
    assert "CARNIVORE_MCP_URL" in cmd
    assert "development-channels" not in cmd and "X-Carnivore-Channel" not in cmd
    assert "CARNIVORE_MCP_CHANNEL" not in cmd


def test_setting_on_adds_one_flag_token_and_the_header_to_a_claude_pane(launcher) -> None:
    cmd = launcher(channels=True).get_agent_command("claude", pane_launch=True)
    assert FLAG in cmd and "CARNIVORE_MCP_CHANNEL" in cmd


@pytest.mark.parametrize("family,pane,enabled", [("codex", True, True), ("claude", False, True), ("claude", True, False)])
def test_setting_on_adds_nothing_to_codex_a_headless_run_or_a_disabled_endpoint(launcher, family, pane, enabled) -> None:
    cmd = launcher(enabled=enabled, channels=True).get_agent_command(family, pane_launch=pane)
    assert "development-channels" not in cmd and "X-Carnivore-Channel" not in cmd
    assert "CARNIVORE_MCP_CHANNEL" not in cmd


def test_claude_args_with_channel_and_the_wrapper_comparison_ignores_the_flag() -> None:
    config, flag = mcp_launch.claude_args(channel=True)
    assert flag == FLAG
    server = json.loads(config.split("=", 1)[1])["mcpServers"]["carnivore"]
    assert server["env"]["CARNIVORE_MCP_CHANNEL"] == "1"
    http = json.loads(mcp_launch.claude_args(channel=True, bridge_script=None)[0].split("=", 1)[1])
    assert http["mcpServers"]["carnivore"]["headers"]["X-Carnivore-Channel"] == "1"
    assert mcp_launch.CLAUDE_DEV_CHANNELS_FLAG in PER_RUN_FLAGS



def test_capability_only_for_a_channel_launch() -> None:
    assert "experimental" not in protocol.server_capabilities(False)
    assert protocol.server_capabilities(True)["experimental"] == {"claude/channel": {}}


def test_initialize_declares_the_channel_only_with_the_header_and_the_setting(env, channels_on) -> None:
    client, mgr, _cfg = env
    init = _rpc("initialize", {"protocolVersion": "2025-11-25"})
    plain = client.post("/mcp", json=init, headers=_hdr(mgr)).json()["result"]["capabilities"]
    asked = client.post("/mcp", json=init, headers={**_hdr(mgr), **CHANNEL}).json()["result"]["capabilities"]
    channels_on.channels = False
    off = client.post("/mcp", json=init, headers={**_hdr(mgr), **CHANNEL}).json()["result"]["capabilities"]
    assert "experimental" not in plain and "experimental" not in off
    assert asked["experimental"] == {"claude/channel": {}}


def test_a_channel_launch_is_told_what_a_channel_event_is(env, channels_on) -> None:
    client, mgr, _cfg = env
    init = _rpc("initialize", {"protocolVersion": "2025-11-25"})
    asked = client.post("/mcp", json=init, headers={**_hdr(mgr), **CHANNEL}).json()["result"]["instructions"]
    plain = client.post("/mcp", json=init, headers=_hdr(mgr)).json()["result"]["instructions"]
    assert 'CHANNEL EVENTS' in asked and 'source_kind="huddle"' in asked and "task_manager_changes" in asked
    assert "CHANNEL EVENTS" not in plain


def test_get_stays_405_unless_a_channel_launch_with_the_setting_on(env, channels_on, registry) -> None:
    client, mgr, _cfg = env
    assert client.get("/mcp", headers=_hdr(mgr)).status_code == 405
    channels_on.channels = False
    assert client.get("/mcp", headers={**_hdr(mgr), **CHANNEL}).status_code == 405
    assert registry.count() == 0


def test_a_channel_get_with_a_bad_token_is_refused(env, channels_on, registry) -> None:
    client, mgr, _cfg = env
    assert client.get("/mcp", headers={**_hdr(mgr, token="nope"), **CHANNEL}).status_code == 401
    assert registry.count() == 0


def test_a_channel_get_streams_under_the_tokens_tmux_name_and_unregisters_when_it_ends(
        env, channels_on, registry, monkeypatch) -> None:
    client, mgr, _cfg = env
    seen = []
    real_open = registry.open

    def open_and_push(tmux_name, session_id):
        stream = real_open(tmux_name, session_id)
        seen.append(tmux_name)
        assert registry.push(tmux_name, "the huddle changed", {"source_kind": "huddle", "bad-key": "x"})
        return stream

    monkeypatch.setattr(registry, "open", open_and_push)
    with client.stream("GET", "/mcp", headers={**_hdr(mgr), **CHANNEL}) as response:
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert seen == ["cloude_a"]
    assert body.startswith(f"retry: {channel.RETRY_MS}\n\n")
    data = json.loads(next(line for line in body.splitlines() if line.startswith("data: "))[6:])
    assert data == {"jsonrpc": "2.0", "method": "notifications/claude/channel",
                    "params": {"content": "the huddle changed", "meta": {"source_kind": "huddle"}}}
    assert registry.count() == 0 and not registry.is_open("cloude_a")



def test_push_goes_to_the_newest_stream_and_a_pane_without_one_declines() -> None:
    reg = channel.ChannelRegistry()
    old, new = reg.open("cloude_a", "ses_a"), reg.open("cloude_a", "ses_a")
    assert reg.push("cloude_a", "x", {}) and new.queue.qsize() == 1 and old.queue.qsize() == 0
    assert not reg.push("cloude_b", "x", {}) and not reg.push(None, "x", {})
    reg.close(new)
    assert reg.push("cloude_a", "y", {}) and old.queue.qsize() == 1
    reg.close(old)
    assert not reg.is_open("cloude_a") and reg.count() == 0


def test_a_full_queue_declines_so_the_caller_pastes() -> None:
    reg = channel.ChannelRegistry()
    reg.open("cloude_a", "ses_a")
    assert all(reg.push("cloude_a", str(i), {}) for i in range(channel.MAX_QUEUED))
    assert not reg.push("cloude_a", "one too many", {})


def test_an_event_queued_at_the_deadline_still_goes_out() -> None:
    async def run() -> list:
        reg = channel.ChannelRegistry()
        body = channel.stream_events("cloude_a", "ses_a", reg, max_s=0.05, keepalive_s=1.0)
        chunks = [await body.__anext__()]
        await asyncio.sleep(0.06)
        assert reg.push("cloude_a", "late", {})
        chunks += [c async for c in body]
        assert reg.count() == 0
        return chunks

    chunks = asyncio.run(run())
    assert any('"content":"late"' in c for c in chunks)



def test_the_channels_route_writes_config_through_the_writer_and_needs_the_owner(env, monkeypatch, tmp_path) -> None:
    from src.api.auth import require_auth
    from src.main import app

    client, mgr, _cfg = env
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"mcp": {"agent_notify": false}}')
    monkeypatch.setattr("src.api.mcp_admin_routes.settings", SimpleNamespace(
        auth_config_file=str(cfg_file), drop_auth_config_cache=lambda: None))
    assert client.put("/api/v1/mcp-admin/channels", json={"enabled": True}, headers=_hdr(mgr)).status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        r = client.put("/api/v1/mcp-admin/channels", json={"enabled": True})
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert r.status_code == 200 and r.json() == {"enabled": True}
    assert json.loads(cfg_file.read_text())["mcp"] == {"agent_notify": False, "channels": True}
    assert McpConfig().channels is False
