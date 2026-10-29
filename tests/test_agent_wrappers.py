from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wrap_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wrap_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config import AgentsConfig, Settings
from src.core.agent_wrappers import (
    AgentWrapper,
    EXAMPLE_WRAPPER_CLD,
    default_wrapper,
    find_wrapper,
    is_valid_wrapper_id,
    render_wrapper_invocation,
    wrapper_scripts_dir,
)


def _settings_with_config(tmp_path: Path, data: dict) -> Settings:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data))
    s = Settings(
        default_working_dir=str(tmp_path / "wd"),
        log_directory=str(tmp_path / "logs"),
        CLOUDE_STATE_DIR=str(tmp_path / "state"),
        totp_secret="x",
        jwt_secret="y",
        auth_config_file=str(config_path),
    )
    return s



def test_wrapper_id_charset():
    assert is_valid_wrapper_id("keyc")
    assert is_valid_wrapper_id("my-wrapper_2")
    assert not is_valid_wrapper_id("Wrp")
    assert not is_valid_wrapper_id("-cld")
    assert not is_valid_wrapper_id("keyc wrapper")
    assert not is_valid_wrapper_id("")


def test_wrapper_rejects_blank_script():
    with pytest.raises(ValidationError):
        AgentWrapper(id="foo", label="foo", script="   ")


def test_wrapper_rejects_bad_id():
    with pytest.raises(ValidationError):
        AgentWrapper(id="Bad Id!", label="x", script="claude")



def test_find_and_default_wrapper():
    w1 = AgentWrapper(id="claude", label="claude", script="claude", default=False)
    w2 = AgentWrapper(id="keyc", label="keyc", script='keyc "$@"', default=True)
    wrappers = [w1, w2]
    assert find_wrapper(wrappers, "keyc") is w2
    assert find_wrapper(wrappers, "nope") is None
    assert default_wrapper(wrappers) is w2
    assert default_wrapper([w1]) is w1
    assert default_wrapper([]) is None


def test_default_wrapper_first_in_list_when_none_marked():
    w1 = AgentWrapper(id="a", label="a", script="a")
    w2 = AgentWrapper(id="b", label="b", script="b")
    assert default_wrapper([w1, w2]) is w1



def test_render_source_only_mode_no_model(tmp_path):
    w = AgentWrapper(id="claude", label="claude", script="claude --dangerously-skip-permissions")
    cmd = render_wrapper_invocation(w, tmp_path)
    assert cmd.startswith("zsh -c ")
    assert "source ~/.zshrc" in cmd
    script_file = tmp_path / "claude.zsh"
    assert script_file.exists()
    assert script_file.read_text() == "claude --dangerously-skip-permissions"
    assert not cmd.rstrip().endswith("_")


def test_render_source_only_mode_with_model_forwards_as_positional(tmp_path):
    w = AgentWrapper(id="clxor", label="clxor", script='clxor "$@"')
    cmd = render_wrapper_invocation(w, tmp_path, model="openai/gpt-5.6-sol")
    assert cmd.endswith("_ openai/gpt-5.6-sol") or "openai/gpt-5.6-sol" in cmd
    assert " _ " in cmd


def test_render_entry_mode_calls_named_function(tmp_path):
    w = AgentWrapper(id="keyc", label="keyc", script="keyc() ( echo hi )", entry="keyc")
    cmd = render_wrapper_invocation(w, tmp_path)
    assert cmd.count('"$@"') == 2
    assert "keyc" in cmd


def test_wrapper_script_file_permissions(tmp_path):
    w = AgentWrapper(id="keyc", label="keyc", script="echo hi")
    render_wrapper_invocation(w, tmp_path)
    mode = (tmp_path / "keyc.zsh").stat().st_mode & 0o777
    assert mode == 0o600



DISABLE_ALT = "export CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1"


def test_disable_alternate_screen_exports_the_var_before_the_agent_runs(tmp_path):
    w = AgentWrapper(id="claude", label="claude", script="command claude")
    cmd = render_wrapper_invocation(w, tmp_path, disable_alternate_screen=True)
    assert DISABLE_ALT in cmd
    assert cmd.index(DISABLE_ALT) < cmd.index("claude.zsh"), (
        "the export lands after the script is sourced, so the agent it is "
        "meant to configure has already been launched without it"
    )


def test_disable_alternate_screen_off_exports_nothing(tmp_path):
    w = AgentWrapper(id="claude", label="claude", script="command claude")
    off = render_wrapper_invocation(w, tmp_path, disable_alternate_screen=False)
    assert "CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN" not in off
    assert off == render_wrapper_invocation(w, tmp_path)


def test_the_export_survives_into_a_function_style_wrapper(tmp_path):
    w = AgentWrapper(
        id="keyc", label="keyc", script=EXAMPLE_WRAPPER_CLD, entry="keyc"
    )
    cmd = render_wrapper_invocation(w, tmp_path, disable_alternate_screen=True)
    assert cmd.index(DISABLE_ALT) < cmd.rindex("keyc")


def test_settings_disables_the_alternate_screen_for_launches_by_default(tmp_path):
    config_data = {
        "agents": {
            "wrappers": [
                {
                    "id": "claude",
                    "label": "claude",
                    "script": "command claude",
                    "default": True,
                }
            ]
        }
    }
    s = _settings_with_config(tmp_path, config_data)
    assert s.load_auth_config().session.disable_alternate_screen is True
    assert DISABLE_ALT in s.get_agent_command("claude")


def test_turning_the_setting_off_removes_the_export_from_the_launch(tmp_path):
    config_data = {
        "session": {"disable_alternate_screen": False},
        "agents": {
            "wrappers": [
                {
                    "id": "claude",
                    "label": "claude",
                    "script": "command claude",
                    "default": True,
                }
            ]
        },
    }
    s = _settings_with_config(tmp_path, config_data)
    assert s.load_auth_config().session.disable_alternate_screen is False
    assert "CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN" not in s.get_agent_command("claude")



def test_real_cld_body_round_trips_byte_for_byte_and_resolves(tmp_path):
    config_data = {
        "agents": {
            "wrappers": [
                {
                    "id": "keyc",
                    "label": "keyc (subscription)",
                    "script": EXAMPLE_WRAPPER_CLD,
                    "entry": "keyc",
                    "description": "real keyc body",
                    "default": True,
                }
            ]
        }
    }
    s = _settings_with_config(tmp_path, config_data)
    loaded_wrappers = s.load_auth_config().agents.wrappers
    assert len(loaded_wrappers) == 1
    assert loaded_wrappers[0].script == EXAMPLE_WRAPPER_CLD

    resolved = s.get_agent_command("claude")
    assert resolved.startswith("zsh -c ")

    script_path = wrapper_scripts_dir(str(s.get_state_dir())) / "keyc.zsh"
    assert script_path.exists()
    on_disk = script_path.read_text()
    assert on_disk == EXAMPLE_WRAPPER_CLD, "script file must match the pasted body byte-for-byte"

    assert "keyc() (" in on_disk
    assert "command claude --dangerously-skip-permissions" in on_disk

    assert str(script_path) in resolved or "keyc.zsh" in resolved
    assert '"$@"' in resolved


def test_real_cld_body_with_model_produces_well_formed_invocation(tmp_path):
    config_data = {
        "agents": {
            "wrappers": [
                {
                    "id": "keyc",
                    "label": "keyc",
                    "script": EXAMPLE_WRAPPER_CLD,
                    "entry": "keyc",
                    "default": True,
                    "accepts_model": True,
                }
            ]
        }
    }
    s = _settings_with_config(tmp_path, config_data)
    resolved = s.get_agent_command("claude", model="some-model")
    assert resolved.startswith("zsh -c '")
    assert resolved.rstrip().endswith("some-model")
    import shlex
    tokens = shlex.split(resolved)
    assert tokens[0] == "zsh"
    assert tokens[1] == "-c"
    assert "keyc" in tokens[2]



def test_reserved_types_unaffected_by_wrappers(tmp_path):
    config_data = {
        "agents": {
            "codex_command": "never read",
            "hermes_command": "never read",
            "openclaw_command": "never read",
            "wrappers": [
                {"id": "claude", "label": "claude", "script": "claude", "default": True}
            ],
        }
    }
    from src.core.shell_init import RC_SOURCE

    s = _settings_with_config(tmp_path, config_data)
    for family, wid in (("codex", "codex-default"), ("hermes", "hermes-default"),
                        ("openclaw", "openclaw-default"), ("shell", "shell-default")):
        command = s.get_agent_command(family)
        standard = {"codex": 'codex "$@"', "shell": 'exec "${SHELL:-/bin/sh}" -i "$@"'}
        assert (standard[family] if family in standard else f"{wid}.zsh") in command, family
        assert "never read" not in command
        assert (RC_SOURCE in command) is (family != "shell"), family
    assert s.get_agent_command("codex").endswith("_ --no-alt-screen")


def test_explicit_wrapper_id_as_agent_type_selects_that_wrapper(tmp_path):
    config_data = {
        "agents": {
            "wrappers": [
                {"id": "claude", "label": "claude", "script": "claude", "default": True},
                {"id": "keyc", "label": "keyc", "script": 'keyc "$@"', "default": False},
            ]
        }
    }
    s = _settings_with_config(tmp_path, config_data)
    resolved = s.get_agent_command("keyc")
    script_path = wrapper_scripts_dir(str(s.get_state_dir())) / "keyc.zsh"
    assert script_path.read_text() == 'keyc "$@"'
    assert "keyc.zsh" in resolved


def test_unknown_agent_type_falls_back_to_default_wrapper(tmp_path):
    config_data = {
        "agents": {
            "wrappers": [
                {"id": "claude", "label": "claude", "script": "claude", "default": True},
            ]
        }
    }
    s = _settings_with_config(tmp_path, config_data)
    resolved = s.get_agent_command("totally-unknown-type")
    assert "claude.zsh" in resolved


def test_no_wrappers_launches_the_standard_claude_wrapper(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {}})
    command = s.get_agent_command("claude")
    assert 'command claude --dangerously-skip-permissions "$@"' in command
    assert "keyc" not in command.replace("claude", "")
    with_model = s.get_agent_command("claude", model="my-model")
    assert '--model my-model "$@"' in with_model


def test_the_retired_claude_command_is_never_read(tmp_path):
    config_data = {"agents": {"claude_command": "claude --retired-flag"}}
    s = _settings_with_config(tmp_path, config_data)
    resolved = s.get_agent_command("claude")
    assert "--retired-flag" not in resolved
    assert 'command claude --dangerously-skip-permissions "$@"' in resolved


def test_wrappers_present_take_priority_over_claude_command():
    agents = AgentsConfig(
        claude_command="should not be used",
        wrappers=[AgentWrapper(id="claude", label="claude", script="the wrapper wins", default=True)],
    )
    assert agents.wrappers[0].script == "the wrapper wins"



def _claude_ids(result):
    return [w["id"] for w in result if (w.get("family") or "claude") == "claude"]


def test_add_wrapper_persists_and_rejects_duplicate(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {}})
    w = AgentWrapper(id="keyc", label="keyc", script='keyc "$@"')
    result = s.add_wrapper(w)
    assert _claude_ids(result) == ["claude", "keyc"]

    with pytest.raises(ValueError, match="already exists"):
        s.add_wrapper(w)


def test_add_wrapper_rejects_reserved_id(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {}})
    w = AgentWrapper(id="codex", label="codex", script="codex")
    with pytest.raises(ValueError, match="reserved"):
        s.add_wrapper(w)


def test_add_wrapper_default_flag_exclusive(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {}})
    s.add_wrapper(AgentWrapper(id="a", label="a", script="a", default=True))
    result = s.add_wrapper(AgentWrapper(id="b", label="b", script="b", default=True))
    defaults = [w for w in result if w["default"] and w["id"] in _claude_ids(result)]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "b"


def test_update_wrapper_requires_matching_id(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {}})
    s.add_wrapper(AgentWrapper(id="keyc", label="keyc", script="a"))
    with pytest.raises(ValueError, match="cannot be changed"):
        s.update_wrapper("keyc", AgentWrapper(id="other", label="x", script="b"))


def test_update_wrapper_replaces_fields(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {}})
    s.add_wrapper(AgentWrapper(id="keyc", label="keyc", script="old"))
    result = s.update_wrapper("keyc", AgentWrapper(id="keyc", label="keyc v2", script="new"))
    updated = next(w for w in result if w["id"] == "keyc")
    assert updated["script"] == "new"
    assert updated["label"] == "keyc v2"


def test_delete_wrapper_promotes_new_default(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {"wrappers": [
        {"id": "a", "label": "a", "script": "a", "default": True},
        {"id": "b", "label": "b", "script": "b", "default": False},
    ]}})
    result = s.delete_wrapper("a")
    assert _claude_ids(result) == ["b"]
    assert next(w for w in result if w["id"] == "b")["default"] is True


def test_deleting_a_familys_last_wrapper_brings_its_standard_one_back(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {"wrappers": [
        {"id": "only", "label": "only", "script": "claude", "default": True},
    ]}})
    result = s.delete_wrapper("only")
    assert _claude_ids(result) == ["claude"]
    assert next(w for w in result if w["id"] == "claude")["default"] is True


def test_delete_wrapper_not_found(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {}})
    with pytest.raises(ValueError, match="not found"):
        s.delete_wrapper("nope")


def test_set_default_wrapper(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {}})
    s.add_wrapper(AgentWrapper(id="a", label="a", script="a", default=True))
    s.add_wrapper(AgentWrapper(id="b", label="b", script="b", default=False))
    result = s.set_default_wrapper("b")
    by_id = {w["id"]: w for w in result}
    assert by_id["a"]["default"] is False
    assert by_id["b"]["default"] is True


def test_wrapper_crud_writes_backup(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {}})
    s.add_wrapper(AgentWrapper(id="keyc", label="keyc", script="a"))
    backup = Path(s.auth_config_file).with_suffix(".json.bak")
    assert backup.exists()
    assert not Path(str(Path(s.auth_config_file)) + ".tmp").exists()



def _wrapper(wid, **kw):
    base = {"id": wid, "label": wid, "script": f'{wid} "$@"', "default": False}
    base.update(kw)
    return base


def test_model_is_dropped_for_a_wrapper_that_does_not_accept_one(tmp_path):
    config_data = {"agents": {"wrappers": [_wrapper("keyc", default=True)]}}
    s = _settings_with_config(tmp_path, config_data)
    with_model = s.get_agent_command("keyc", model="anthropic/claude-opus-4")
    without = s.get_agent_command("keyc")
    assert with_model == without
    assert "anthropic/claude-opus-4" not in with_model


def test_model_is_forwarded_for_a_wrapper_that_accepts_one(tmp_path):
    config_data = {
        "agents": {"wrappers": [_wrapper("clxor", default=True, accepts_model=True)]}
    }
    s = _settings_with_config(tmp_path, config_data)
    resolved = s.get_agent_command("clxor", model="anthropic/claude-opus-4")
    assert resolved.rstrip().endswith("anthropic/claude-opus-4")


def test_accepts_model_defaults_false_so_existing_wrappers_are_unchanged(tmp_path):
    config_data = {"agents": {"wrappers": [_wrapper("legacy", default=True)]}}
    s = _settings_with_config(tmp_path, config_data)
    agents = s.load_auth_config().agents
    assert agents.wrappers[0].accepts_model is False


def test_no_wrappers_never_hands_the_model_to_the_standard_claude(tmp_path):
    s = _settings_with_config(tmp_path, {"agents": {"claude_command": ""}})
    resolved = s.get_agent_command("claude", model="some/model")
    assert "clxor" not in resolved
    assert '--model some/model "$@"' in resolved
