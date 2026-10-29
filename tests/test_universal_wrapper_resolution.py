from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

_WD = tempfile.mkdtemp(prefix="cc_uw_wd_")
_LOGS = tempfile.mkdtemp(prefix="cc_uw_logs_")
os.environ.setdefault("DEFAULT_WORKING_DIR", _WD)
os.environ.setdefault("LOG_DIRECTORY", _LOGS)
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config import Settings
from tests.helpers.wrapper_seeds import launches


def _wrapper(wid, family="claude", **kw):
    base = {
        "id": wid,
        "family": family,
        "label": wid,
        "script": f"run-{wid}",
        "entry": None,
        "description": None,
        "default": False,
        "accepts_model": False,
    }
    base.update(kw)
    return base


def _settings(tmp_path, wrappers=None, **agent_overrides):
    agents = {
        "claude_command": "",
        "codex_command": "codex",
        "hermes_command": "hermes",
        "openclaw_command": "openclaw tui",
    }
    agents.update(agent_overrides)
    if wrappers is not None:
        agents["wrappers"] = wrappers
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"config_version": 3, "agents": agents, "projects": []}))
    return Settings(
        default_working_dir=str(tmp_path),
        log_directory=str(tmp_path / "logs"),
        totp_secret="x",
        jwt_secret="y",
        auth_config_file=str(config_path),
    )



@pytest.mark.parametrize("agent_type,expected", [
    ("codex", "codex-default.zsh"),
    ("hermes", "hermes-default.zsh"),
    ("openclaw", "openclaw-default.zsh"),
    ("shell", "shell-default.zsh"),
])
def test_bare_family_types_launch_their_standard_wrapper(tmp_path, agent_type, expected):
    s = _settings(tmp_path, wrappers=[_wrapper("cld", default=True)],
                  codex_command="never-read", hermes_command="never-read",
                  openclaw_command="never-read", shell_command="never-read")
    out = s.get_agent_command(agent_type)
    assert launches(out, expected)
    assert "never-read" not in out
    assert "cld.zsh" not in out


def test_an_existing_shell_session_still_launches_a_shell(tmp_path):
    from src.core.agent_families import get_family
    from src.core.shell_init import RC_SOURCE

    s = _settings(tmp_path, wrappers=[_wrapper("cld", default=True)])
    out = s.get_agent_command("shell")
    assert launches(out, "shell-default.zsh") and get_family("shell").default_script in out
    assert RC_SOURCE not in out


def test_claude_launch_uses_the_default_claude_wrapper(tmp_path):
    s = _settings(tmp_path, wrappers=[
        _wrapper("claude-skip-permissions", default=True),
        _wrapper("cld"),
    ])
    out = s.get_agent_command("claude")
    assert "claude-skip-permissions.zsh" in out


def test_an_explicit_wrapper_id_wins_over_the_default(tmp_path):
    s = _settings(tmp_path, wrappers=[
        _wrapper("claude-skip-permissions", default=True),
        _wrapper("cld"),
    ])
    assert "cld.zsh" in s.get_agent_command("cld")


def test_no_wrappers_launches_the_standard_claude_wrapper(tmp_path):
    s = _settings(tmp_path, wrappers=[], claude_command="claude --foo")
    out = s.get_agent_command("claude")
    assert out.startswith("zsh -c ")
    assert "source ~/.zshrc" in out
    assert launches(out, "claude.zsh")
    assert "claude --foo" not in out



def test_a_codex_wrapper_takes_precedence_over_codex_command(tmp_path):
    s = _settings(tmp_path, wrappers=[_wrapper("my-codex", family="codex", default=True)])
    out = s.get_agent_command("codex")
    assert "my-codex.zsh" in out
    assert out != "codex"


def test_a_codex_wrapper_does_not_affect_the_claude_launch(tmp_path):
    s = _settings(tmp_path, wrappers=[
        _wrapper("my-codex", family="codex", default=True),
    ])
    out = s.get_agent_command("claude")
    assert launches(out, "claude.zsh")
    assert "my-codex" not in out


def test_a_claude_wrapper_does_not_affect_the_codex_launch(tmp_path):
    s = _settings(tmp_path, wrappers=[_wrapper("cld", default=True)])
    out = s.get_agent_command("codex")
    assert launches(out, "codex-default.zsh") and out.endswith("_ --no-alt-screen")
    assert "cld.zsh" not in out


def test_each_family_resolves_its_own_default_independently(tmp_path):
    s = _settings(tmp_path, wrappers=[
        _wrapper("cld-a", default=False),
        _wrapper("cld-b", default=True),
        _wrapper("codex-a", family="codex", default=True),
        _wrapper("codex-b", family="codex", default=False),
    ])
    assert "cld-b.zsh" in s.get_agent_command("claude")
    assert "codex-a.zsh" in s.get_agent_command("codex")


def test_a_shell_wrapper_replaces_shell_command(tmp_path):
    s = _settings(tmp_path, wrappers=[_wrapper("fancy-shell", family="shell", default=True)])
    assert "fancy-shell.zsh" in s.get_agent_command("shell")


def test_a_family_with_no_default_uses_its_first_wrapper(tmp_path):
    s = _settings(tmp_path, wrappers=[
        _wrapper("codex-first", family="codex"),
        _wrapper("codex-second", family="codex"),
    ])
    assert "codex-first.zsh" in s.get_agent_command("codex")



def test_a_model_is_dropped_for_a_wrapper_that_does_not_accept_one(tmp_path):
    s = _settings(tmp_path, wrappers=[_wrapper("cld", default=True, accepts_model=False)])
    out = s.get_agent_command("cld", model="vendor/m-1")
    assert "vendor/m-1" not in out


def test_a_model_is_forwarded_to_a_wrapper_that_accepts_one(tmp_path):
    s = _settings(tmp_path, wrappers=[_wrapper("cldor", default=True, accepts_model=True)])
    assert "vendor/m-1" in s.get_agent_command("cldor", model="vendor/m-1")


def test_model_gating_applies_to_a_non_claude_family_too(tmp_path):
    s = _settings(tmp_path, wrappers=[
        _wrapper("codex-routed", family="codex", default=True, accepts_model=True),
    ])
    assert "vendor/m-1" in s.get_agent_command("codex", model="vendor/m-1")



def test_a_wrapper_dict_with_no_family_key_still_resolves_as_claude(tmp_path):
    legacy = {
        "id": "cld",
        "label": "cld",
        "script": "cld",
        "entry": None,
        "description": None,
        "default": True,
        "accepts_model": False,
    }
    s = _settings(tmp_path, wrappers=[legacy])
    assert "cld.zsh" in s.get_agent_command("claude")
    assert launches(s.get_agent_command("shell"), "shell-default.zsh")



def test_family_summaries_cover_every_family_and_report_wrapper_counts(tmp_path):
    from src.core.agent_families import AGENT_FAMILY_NAMES

    s = _settings(tmp_path, wrappers=[
        _wrapper("cld", default=True),
        _wrapper("my-codex", family="codex", default=True),
    ])
    summary = s.get_settings_summary()["agents"]
    by_name = {f["name"]: f for f in summary["families"]}
    assert set(by_name) == set(AGENT_FAMILY_NAMES)
    assert by_name["claude"]["wrapper_count"] == 1
    assert by_name["codex"]["wrapper_count"] == 1
    assert by_name["hermes"]["wrapper_count"] == 0


def test_family_summary_names_each_familys_default_wrapper(tmp_path):
    s = _settings(tmp_path, wrappers=[
        _wrapper("cld-a"), _wrapper("cld-b", default=True),
        _wrapper("codex-first", family="codex"),
    ])
    by_name = {f["name"]: f for f in s.get_settings_summary()["agents"]["families"]}
    assert by_name["claude"]["default_wrapper"] == "cld-b"
    assert by_name["codex"]["default_wrapper"] == "codex-first"
    assert by_name["hermes"]["default_wrapper"] is None
    assert "hermes-default.zsh" in by_name["hermes"]["effective_command"]
