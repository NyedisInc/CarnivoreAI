
from __future__ import annotations

import inspect
import json
import os
import shlex
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
from src.core import session_agent_choice


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path))
    s = Settings()
    monkeypatch.setattr(s, "port", 8123)

    def set_enabled(enabled: bool) -> Settings:
        monkeypatch.setattr(Settings, "load_auth_config", lambda self: SimpleNamespace(
            agents=AgentsConfig(), session=SessionConfig(), mcp=McpConfig(enabled=enabled)))
        return s

    return set_enabled


@pytest.mark.parametrize("family", ["claude", "codex"])
def test_pane_launch_registers_and_others_do_not(cfg, family) -> None:
    s = cfg(True)
    pane = s.get_agent_command(family, extra_args=["--x"], pane_launch=True)
    assert ("CARNIVORE_MCP_URL" if family == "claude" else "127.0.0.1:8123/mcp") in pane
    assert "carnivore" not in s.get_agent_command(family, extra_args=["--x"])


def test_kill_switch_and_unresolved_port_emit_nothing(cfg) -> None:
    assert "carnivore" not in cfg(False).get_agent_command("codex", pane_launch=True)
    assert mcp_launch.registration_url(True, True, None) is None
    assert mcp_launch.registration_url(False, True, 8123) is None


def test_codex_overrides_precede_a_resume_subcommand(cfg) -> None:
    cmd = cfg(True).get_agent_command("codex", extra_args=["resume", "abc"], pane_launch=True)
    outer = shlex.split(cmd)
    inner = shlex.split(outer[2])
    assert any(word.endswith("codex_supervisor.py") for word in inner)
    plan = json.loads(next(word for word in inner if word.startswith('{"server":')))
    assert "mcp_servers.carnivore.url=\"http://127.0.0.1:8123/mcp\"" in plan["server"]
    assert plan["tui"][:2] == ["resume", "abc"]
    assert "resume" not in plan["server"]


def test_claude_config_is_one_token_carrying_no_secret() -> None:
    (arg,) = mcp_launch.claude_args()
    assert arg.startswith("--mcp-config={") and "${CLOUDECODE_HOOK_TOKEN}" in arg


def test_bridge_command_is_the_payload_python_only_when_the_shell_set_it(monkeypatch, tmp_path) -> None:
    py = tmp_path / "python3"
    py.write_text("#!/bin/sh\n")
    py.chmod(0o755)
    monkeypatch.delenv(mcp_launch.PAYLOAD_PYTHON_ENV, raising=False)
    assert mcp_launch.bridge_command() == "python3"
    monkeypatch.setenv(mcp_launch.PAYLOAD_PYTHON_ENV, str(py))
    assert mcp_launch.bridge_command() == str(py)
    server = json.loads(mcp_launch.claude_args()[0].split("=", 1)[1])["mcpServers"]["carnivore"]
    assert server["command"] == str(py)
    monkeypatch.setenv(mcp_launch.PAYLOAD_PYTHON_ENV, str(tmp_path / "missing"))
    assert mcp_launch.bridge_command() == "python3"


def test_payload_bridge_config_carries_the_bytecode_variable_and_a_dev_python_does_not(monkeypatch, tmp_path) -> None:
    py = tmp_path / "python3"
    py.write_text("#!/bin/sh\n")
    py.chmod(0o755)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", "/C/pycache")
    monkeypatch.delenv(mcp_launch.PAYLOAD_PYTHON_ENV, raising=False)
    dev = json.loads(mcp_launch.claude_args()[0].split("=", 1)[1])["mcpServers"]["carnivore"]
    assert "PYTHONPYCACHEPREFIX" not in dev["env"]
    monkeypatch.setenv(mcp_launch.PAYLOAD_PYTHON_ENV, str(py))
    server = json.loads(mcp_launch.claude_args()[0].split("=", 1)[1])["mcpServers"]["carnivore"]
    assert server["env"]["PYTHONPYCACHEPREFIX"] == "/C/pycache"
    monkeypatch.delenv("PYTHONPYCACHEPREFIX")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    server = json.loads(mcp_launch.claude_args()[0].split("=", 1)[1])["mcpServers"]["carnivore"]
    assert server["env"]["PYTHONDONTWRITEBYTECODE"] == "1" and "PYTHONPYCACHEPREFIX" not in server["env"]


def test_claude_registers_the_stdio_bridge_with_the_pane_credentials_in_env_only() -> None:
    (arg,) = mcp_launch.claude_args()
    server = json.loads(arg.split("=", 1)[1])["mcpServers"]["carnivore"]
    assert server["type"] == "stdio" and server["command"] == "python3"
    assert server["args"] == [str(mcp_launch.BRIDGE_SCRIPT)] and mcp_launch.BRIDGE_SCRIPT.is_file()
    assert server["env"] == {"CARNIVORE_MCP_URL": "${CARNIVORE_MCP_URL}",
                             "CLOUDECODE_HOOK_TOKEN": "${CLOUDECODE_HOOK_TOKEN}",
                             "CLOUDECODE_SESSION_ID": "${CLOUDECODE_SESSION_ID}"}
    assert "headers" not in server and "Bearer" not in json.dumps(server["args"])


def test_a_missing_bridge_script_falls_back_to_the_http_registration(tmp_path) -> None:
    (arg,) = mcp_launch.claude_args(bridge_script=tmp_path / "gone.py")
    server = json.loads(arg.split("=", 1)[1])["mcpServers"]["carnivore"]
    assert server["type"] == "http" and server["url"] == "${CARNIVORE_MCP_URL}"


def test_the_agent_choice_renders_through_the_one_pane_launch_builder() -> None:
    source = inspect.getsource(session_agent_choice)
    assert source.count("settings_obj.pane_launch_command(") == 2 and "get_agent_command(" not in source
