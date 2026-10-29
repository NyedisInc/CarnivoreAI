
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.blueprints_helpers import client_for

# ruff: noqa: E402
from src.config import agent_command as agent_command_module
from src.config.agents import AgentsConfig
from src.core.agent_wrappers import AgentWrapper

HOSTILE = "fix it; touch PWNED $(touch PWNED2) `touch PWNED3` 'quoted' \"dq\" && echo $HOME"

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh renders the launch")


def _fake_cli(tmp_path: Path) -> Path:
    cli = tmp_path / "fakecli"
    cli.write_text(f"#!/bin/sh\nprintf '%s\\0' \"$@\" > '{tmp_path / 'argv.bin'}'\n")
    cli.chmod(0o755)
    return cli


def _execute(command: str, tmp_path: Path) -> list:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    subprocess.run(["/bin/sh", "-c", command], cwd=tmp_path, check=True, timeout=30,
                   env={"HOME": str(home), "PATH": "/usr/bin:/bin"})
    raw = (tmp_path / "argv.bin").read_bytes().decode("utf-8")
    return raw.split("\0")[:-1]


def _render(agent_type, agents, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_command_module, "mcp_config_args", lambda: [])
    return agent_command_module.agent_command(
        agent_type, agents=agents, resolve_state_dir=lambda: str(tmp_path / "state"),
        disable_alternate_screen=lambda: False, extra_args=[HOSTILE])


def _no_side_effects(tmp_path: Path) -> None:
    for name in ("PWNED", "PWNED2", "PWNED3"):
        assert not (tmp_path / name).exists(), f"the shell ran part of the prompt ({name})"


def test_a_folded_codex_command_gets_the_prompt_as_one_literal_argument(tmp_path, monkeypatch):
    from src.core.launch_wrappers.family_defaults import script_from_command

    cli = _fake_cli(tmp_path)
    wrapper = AgentWrapper(id="cx", family="codex", label="codex",
                           script=script_from_command("codex", f"{cli} --yolo"))
    agents = AgentsConfig(wrappers=[wrapper])
    argv = _execute(_render("codex", agents, tmp_path, monkeypatch), tmp_path)
    assert argv == [HOSTILE, "--yolo"]
    _no_side_effects(tmp_path)


def test_a_folded_claude_command_gets_the_prompt_as_one_literal_argument(tmp_path, monkeypatch):
    from src.core.launch_wrappers.family_defaults import script_from_command

    cli = _fake_cli(tmp_path)
    wrapper = AgentWrapper(id="c", family="claude", label="c",
                           script=script_from_command("claude", str(cli)))
    agents = AgentsConfig(wrappers=[wrapper])
    argv = _execute(_render("claude", agents, tmp_path, monkeypatch), tmp_path)
    assert argv == [HOSTILE]
    _no_side_effects(tmp_path)


def test_a_wrapper_forwards_the_prompt_as_one_literal_argument(tmp_path, monkeypatch):
    cli = _fake_cli(tmp_path)
    wrapper = AgentWrapper(id="fakew", family="claude", label="fakew", script=f'{cli} "$@"')
    agents = AgentsConfig(wrappers=[wrapper])
    argv = _execute(_render("fakew", agents, tmp_path, monkeypatch), tmp_path)
    assert argv == [HOSTILE]
    _no_side_effects(tmp_path)


def test_the_create_route_passes_the_prompt_once_with_the_resolved_type(tmp_path, monkeypatch):
    env = client_for(tmp_path, monkeypatch)
    response = env.client.post("/api/v1/sessions", json={
        "working_dir": str(tmp_path), "agent_type": "codex", "opening_prompt": HOSTILE})
    assert response.status_code == 201, response.text
    call = env.manager.calls[-1]
    assert call["agent_extra_args"] == [HOSTILE] and call["agent_type"] == "codex"


def test_no_prompt_means_no_extra_arguments(tmp_path, monkeypatch):
    env = client_for(tmp_path, monkeypatch)
    response = env.client.post("/api/v1/sessions", json={"working_dir": str(tmp_path)})
    assert response.status_code == 201, response.text
    assert env.manager.calls[-1]["agent_extra_args"] == []


@pytest.mark.parametrize("body", [
    {"agent_type": "shell", "opening_prompt": "list the files please"},
    {"agent_type": "codex", "opening_prompt": "go on then", "auto_start_claude": False},
])
def test_a_prompt_the_launch_cannot_deliver_is_a_400(tmp_path, monkeypatch, body):
    env = client_for(tmp_path, monkeypatch)
    response = env.client.post("/api/v1/sessions", json={"working_dir": str(tmp_path), **body})
    assert response.status_code == 400, response.text
    assert env.manager.calls == []


def test_a_restart_never_sees_the_prompt():
    root = Path(__file__).resolve().parents[1] / "src"
    manager = (root / "core" / "session_manager.py").read_text()
    uses = [line.strip() for line in manager.splitlines()
            if "agent_extra_args" in line and not line.strip().startswith(("#", "``"))]
    assert uses == ["agent_extra_args: Optional[List[str]] = None,",
                    "``agent_extra_args`` appends arguments to the resolved agent command",
                    "extra_args=(agent_extra_args or []) + name_args,"] or all(
        "self." not in u and "INSERT" not in u and "UPDATE" not in u for u in uses)
    for module in ("session_respawn.py", "session_resume_target.py", "session_recreate.py"):
        assert "opening_prompt" not in (root / "core" / module).read_text()
