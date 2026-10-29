
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core.config_migration import migrate_config_file
from src.core.session_agent_choice import CHOICE_ACCEPTED, validate_agent_choice
from src.core.session_restart import resume_arguments
from tests.helpers.wrapper_seeds import stored_wrappers

UUID = "0198c8f0-1111-7222-8333-944445555666"

V5_CONFIG = {
    "config_version": 5,
    "projects": [],
    "mcp": {"enabled": False},
    "agents": {
        "codex_command": "codex --yolo",
        "wrappers": [
            {"id": "cld", "family": "claude", "label": "cld",
             "script": 'claude "$@"', "default": True, "accepts_model": False},
        ],
    },
}


@pytest.fixture()
def live_config(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(V5_CONFIG, indent=2))
    assert migrate_config_file(config)["migrated"] is True
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    monkeypatch.setattr(settings, "_auth_config_cache", None)
    settings.ensure_wrapper_defaults()
    yield tmp_path
    settings._auth_config_cache = None


def _argv_of(command: str, tmp_path: Path, binary: str) -> list:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    record = tmp_path / f"argv-{binary}.txt"
    fake = fake_bin / binary
    fake.write_text(f"#!/bin/sh\n: > '{record}'\nfor a in \"$@\"; do printf '%s\\n' \"$a\" >> '{record}'; done\n")
    fake.chmod(0o755)
    subprocess.run(["/bin/sh", "-c", command], check=True, timeout=30,
                   env={"HOME": str(tmp_path), "PATH": f"{fake_bin}:/usr/bin:/bin"})
    return record.read_text().splitlines()


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_type", ["codex", "codex-default"])
async def test_create_and_blueprint_launch_run_the_codex_default(
    live_config, monkeypatch, tmux_test_socket, agent_type
):
    from src.core.db_migration import ensure_db_migrated
    from src.core.session_manager import SessionManager

    real = type(settings).get_agent_command
    seen = []

    def capture(self, *args, **kwargs):
        seen.append(real(self, *args, **kwargs))
        return "sleep 45"

    monkeypatch.setattr(type(settings), "get_agent_command", capture)
    ensure_db_migrated(live_config / "state", 4, "0.8.2")
    work = live_config / "wd"
    work.mkdir()
    token = uuid.uuid4().hex[:8]
    mgr = SessionManager()
    session = None
    try:
        session = await mgr.create_session(
            session_id=f"ses_{token}", working_dir=str(work), auto_start_claude=True,
            agent_type=agent_type, project_name=f"lw{token}",
        )
    finally:
        if session is not None:
            await mgr.destroy_session(session.id)
    assert len(seen) == 1
    assert "codex-default.zsh" in seen[0]
    assert _argv_of(seen[0], live_config, "codex") == ["--no-alt-screen", "--yolo"]


def test_recreate_and_wake_run_the_picked_default_on_the_same_conversation(live_config):
    choice = validate_agent_choice(
        settings, "codex-default", extra_args=resume_arguments(UUID, family="codex"))
    assert choice.verdict == CHOICE_ACCEPTED, choice.detail
    assert _argv_of(choice.command, live_config, "codex") == [
        "resume", UUID, "--no-alt-screen", "--yolo"]


def test_restart_rederives_the_default_with_the_resume_arguments(live_config):
    from src.core.session_manager import SessionManager

    mgr = SessionManager()
    mgr._registry.sessions["ses_lwtest"] = SimpleNamespace(
        id="ses_lwtest", tmux_session="cloude_lwtest", agent_type="codex-default", model=None)
    command = mgr._agent_command_for_tmux_name(
        "cloude_lwtest", extra_args=resume_arguments(UUID, family="codex"))
    assert command is not None
    assert _argv_of(command, live_config, "codex") == [
        "resume", UUID, "--no-alt-screen", "--yolo"]


def test_deleting_the_default_wrapper_brings_the_standard_one_back(live_config):
    settings.delete_wrapper("codex-default")
    on_disk = json.loads(Path(settings.auth_config_file).read_text())
    codex = [w for w in stored_wrappers(on_disk) if w["family"] == "codex"]
    assert [(w["id"], w["script"], w["default"]) for w in codex] == [
        ("codex-default", 'codex "$@"', True)]
    assert _argv_of(settings.get_agent_command("codex"), live_config, "codex") == [
        "--no-alt-screen"]


def test_a_launch_after_a_hand_edit_removed_the_family_still_runs_its_standard(live_config):
    config = Path(settings.auth_config_file)
    data = json.loads(config.read_text())
    data["launch_profiles"]["profiles"] = [p for p in data["launch_profiles"]["profiles"] if p["harness"] != "hermes"]
    config.write_text(json.dumps(data))
    settings._auth_config_cache = None

    assert _argv_of(settings.get_agent_command("hermes"), live_config, "hermes") == []
    assert settings.ensure_wrapper_defaults() is True
    hermes = [w["id"] for w in stored_wrappers(json.loads(config.read_text()))
              if w["family"] == "hermes"]
    assert hermes == ["hermes-default"]
