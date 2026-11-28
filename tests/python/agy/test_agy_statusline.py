
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.core.agy import install, state
from src.core.agy.statusline_bridge import render
from src.core.session_token_usage.agy_reader import read_agy_usage

BRIDGE = Path(install.__file__).with_name("statusline_bridge.py")
PAYLOAD = {
    "agent_state": "tool_use", "conversation_id": "c1", "email": "x@example.com", "cycle_mode": "auto",
    "model": {"id": "gemini-4-neon", "display_name": "Gemini 4 Neon (High)", "effort": "high"},
    "context_window": {"total_input_tokens": 100, "total_output_tokens": 20, "context_window_size": 1000,
                       "used_percentage": 12.0, "remaining_percentage": 88.0,
                       "current_usage": {"input_tokens": 90, "cache_read_input_tokens": 30, "output_tokens": 5}},
    "quota": {"gemini-weekly": {"remaining_fraction": 0.5}}, "cost": {"total_usd": 0.25}, "terminal_width": 80,
}


def _run(tmp: Path, payload: dict, pid: str = "4242") -> str:
    out = subprocess.run([sys.executable, "-I", "-S", str(BRIDGE), str(tmp), pid], input=json.dumps(payload),
                         capture_output=True, text=True, check=True)
    return out.stdout


def test_bridge_keeps_state_by_pid_and_draws_the_bar(tmp_path):
    bar = _run(tmp_path, PAYLOAD)
    assert "Gemini 4 Neon (High)" in bar and "quota 50%" in bar and " high" not in bar.split("(High)")[1][:6]
    kept = json.loads((tmp_path / "4242.json").read_text())
    assert kept["conversation_id"] == "c1" and "terminal_width" not in kept
    assert (tmp_path / "4242.json").stat().st_mode & 0o777 == 0o600


def test_bridge_never_fails_on_garbage(tmp_path):
    out = subprocess.run([sys.executable, "-I", "-S", str(BRIDGE), str(tmp_path), "../x"], input="not json",
                         capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout == "" and not list(tmp_path.iterdir())


def test_status_codes_and_quota():
    assert state.status_code({"agent_state": "tool_use"}) == "busy"
    assert state.status_code({"agent_state": "idle"}) == "idle"
    assert state.status_code({"agent_state": "idle", "task_count": 1}) == "busy"
    assert state.status_code({"agent_state": "idle", "subagents": [{"status": "running"}]}) == "busy"
    assert state.status_code({"agent_state": "idle", "task_count": 0, "subagents": [{"status": "completed"}]}) == "idle"
    assert state.status_code({"agent_state": "working", "tool_confirmation_pending": True}) == "waiting"
    assert state.status_code({"agent_state": "authenticating"}) is None
    assert state.status_code(None) is None
    assert state.quota_exhausted({"quota": {"w": {"remaining_fraction": 0}}})
    assert state.quota_exhausted({"quota": {"w": {"remaining_fraction": 0.4, "disabled": True}}})
    assert not state.quota_exhausted({"quota": {"w": {"remaining_fraction": 0.4}}})


def test_token_usage_reads_the_conversation_state(tmp_path):
    _run(state.state_folder(tmp_path), PAYLOAD)
    usage = read_agy_usage(tmp_path, "c1")
    assert usage.family == "agy" and usage.input_tokens == 100 and usage.output_tokens == 20
    assert usage.context_used_tokens == 120 and usage.context_window_tokens == 1000 and usage.cost_estimate_usd == 0.25
    assert read_agy_usage(tmp_path, "other") is None


def test_install_writes_carnivore_command_and_keeps_other_keys(tmp_path):
    home = tmp_path / "agy"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"trustedWorkspaces": ["/a"]}))
    assert install.install(tmp_path / "state", home) == "installed"
    data = json.loads((home / "settings.json").read_text())
    assert data["trustedWorkspaces"] == ["/a"] and install.SCRIPT_NAME in data["statusLine"]["command"]
    assert (tmp_path / "state" / "bin" / install.SCRIPT_NAME).is_file()
    assert install.install(tmp_path / "state", home) == "unchanged"


def test_install_leaves_the_owners_own_command_and_skips_without_agy(tmp_path):
    home = tmp_path / "agy"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"statusLine": {"command": "~/mine.sh"}}))
    assert install.install(tmp_path / "state", home) == "owner_command"
    assert json.loads((home / "settings.json").read_text())["statusLine"]["command"] == "~/mine.sh"
    assert install.install(tmp_path / "state", tmp_path / "missing") == "no_agy"


def test_render_flags_a_pending_confirmation():
    assert "needs you" in render({"tool_confirmation_pending": True})
