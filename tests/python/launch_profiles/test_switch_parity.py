
import copy
import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_switch_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_switch_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.config import Settings, agent_command as agent_command_module  # noqa: E402
from src.core.config_migration import CURRENT_CONFIG_VERSION, migrate_config_dict  # noqa: E402
from src.core.launch_profiles.resolve import (  # noqa: E402
    LaunchProfileNotFound, LaunchRequest, _transparent_codex_yolo, pick_profile,
)
from tests.python.launch_profiles import legacy_render  # noqa: E402
from tests.python.launch_profiles.test_config_migration_v7 import _config  # noqa: E402
from tests.python.launch_profiles.test_resolve_parity import APP_ARGS, _run, _stubs  # noqa: E402

IDS = ["claude", "keyc", "clxor", "codex-yolo", "hermes-default", "openclaw-default", "local-default",
       "shell-default", "codex", "shell", "hermes", "openclaw", "local", "no-such-legacy-value", None]


def _settings(tmp_path: Path, data: dict) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return Settings(default_working_dir=str(tmp_path / "wd"), log_directory=str(tmp_path / "logs"),
                    CLOUDE_STATE_DIR=str(tmp_path / "state"), totp_secret="x", jwt_secret="y", auth_config_file=str(path))


def _v6(alt: bool = False) -> dict:
    data = _config()
    data["providers"] = {"local_host": "192.0.2.13:1234"}
    data["session"] = {"disable_alternate_screen": alt}
    return data


@pytest.fixture(autouse=True)
def _no_shared_mcp(monkeypatch):
    monkeypatch.setattr(agent_command_module, "mcp_config_args", lambda: [])


def test_v7_v8_chain_on_a_v6_config():
    before = _v6()
    frozen = copy.deepcopy(before)
    after, changed = migrate_config_dict(before, False, False)
    assert changed and before == frozen and after["config_version"] == CURRENT_CONFIG_VERSION == 8
    assert [p["id"] for p in after["launch_profiles"]["profiles"]] == [w["id"] for w in frozen["agents"]["wrappers"]]
    assert after["agents"] == frozen["agents"] and after["providers"] == frozen["providers"]
    assert [c["id"] for c in after["byoai"]["connections"]] == ["lmstudio"]
    again, changed_again = migrate_config_dict(after, False, False)
    assert not changed_again and again == after


@pytest.mark.parametrize("alt", [False, True])
@pytest.mark.parametrize("args", [(), APP_ARGS])
@pytest.mark.parametrize("model", [None, "vendor/some-model"])
@pytest.mark.parametrize("agent_type", IDS)
def test_facade_matches_the_wrapper_ladder(tmp_path, agent_type, model, args, alt):
    raw = _v6(alt)
    migrated, _ = migrate_config_dict(copy.deepcopy(raw), False, False)
    for data in (raw, migrated):
        s = _settings(tmp_path / ("m" if data is migrated else "u"), data)
        agents = s.load_auth_config().agents
        try:
            today = legacy_render.legacy_agent_command(
                agent_type, agents=agents, resolve_state_dir=lambda: str(s.get_state_dir()),
                disable_alternate_screen=lambda: alt, model=model, extra_args=list(args))
        except ValueError:
            today = "ValueError"
        try:
            mine = s.get_agent_command(agent_type, model=model, extra_args=list(args))
        except ValueError:
            mine = "ValueError"
        profiles = tuple(s.load_auth_config().launch_profiles.profiles)
        selected = pick_profile(LaunchRequest(profiles=profiles, agent_type=agent_type))
        if mine == "ValueError" or today == "ValueError":
            assert mine == today
            continue
        if selected.custom_command is None or _transparent_codex_yolo(selected):
            continue
        assert mine == today


@pytest.mark.parametrize("args", [(), APP_ARGS])
@pytest.mark.parametrize("alt", [False, True])
@pytest.mark.parametrize("agent_type", ["claude", "shell-default", "shell", None])
def test_structured_seeds_run_with_the_same_argv_and_env(tmp_path, agent_type, args, alt):
    migrated, _ = migrate_config_dict(_v6(alt), False, False)
    s = _settings(tmp_path / "s", migrated)
    today = legacy_render.legacy_agent_command(
        agent_type, agents=s.load_auth_config().agents, resolve_state_dir=lambda: str(s.get_state_dir()),
        disable_alternate_screen=lambda: alt, extra_args=list(args))
    mine = s.get_agent_command(agent_type, extra_args=list(args))
    a, b = _run(mine, tmp_path, "mine"), _run(today, tmp_path, "today")
    assert a["argv"] == b["argv"] and a["env"] == b["env"]


def test_env_is_applied_after_the_rc_and_an_endpoint_unsets_what_it_owns(tmp_path):
    migrated, _ = migrate_config_dict(_v6(), False, False)
    migrated["launch_profiles"]["profiles"] += [
        {"id": "cld-env", "harness": "claude", "label": "env", "env": [{"name": "RC_SET", "value": "from profile"}],
         "custom_command": {"script": 'command claude "$@"', "entry": None}},
        {"id": "claude-lms", "harness": "claude", "label": "lms", "model": {"mode": "fixed", "value": "qwen3"},
         "endpoint": {"mode": "connection", "connection_id": "lmstudio"}},
    ]
    s = _settings(tmp_path / "s", migrated)
    home, _ = _stubs(tmp_path)
    (home / ".zshrc").write_text(
        "export RC_SET=from-rc ANTHROPIC_BASE_URL=https://rc.invalid OPENROUTER_API_KEY=rc-leftover\n")
    env = _run(s.get_agent_command("cld-env"), tmp_path, "env")["env"]
    assert env["RC_SET"] == "from profile"
    env = _run(s.get_agent_command("claude-lms"), tmp_path, "lms")["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://192.0.2.13:1234" and "OPENROUTER_API_KEY" not in env
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "qwen3"
    native = _run(s.get_agent_command("claude"), tmp_path, "native")["env"]
    assert native["ANTHROPIC_BASE_URL"] == "https://rc.invalid"


def test_explicit_unknown_pick_is_refused_and_a_secret_profile_needs_the_create_seam(tmp_path):
    migrated, _ = migrate_config_dict(_v6(), False, False)
    migrated["launch_profiles"]["profiles"].append({"id": "claude-key", "harness": "claude", "label": "k",
                                                    "secrets": [{"name": "MY_API_KEY", "keychain_ref": "carnivore/k"}]})
    s = _settings(tmp_path, migrated)
    assert s.get_agent_command("gone")
    auth = s.load_auth_config()
    with pytest.raises(LaunchProfileNotFound) as err:
        agent_command_module.agent_command(
            "gone", agents=auth.agents, resolve_state_dir=lambda: str(s.get_state_dir()),
            disable_alternate_screen=lambda: False, profiles=tuple(auth.launch_profiles.profiles), explicit=True)
    assert err.value.codes == ("wrapper_needed", "launch_profile_needed")
    with pytest.raises(ValueError, match="Keychain secrets"):
        s.get_agent_command("claude-key")
    from src.api.session_sleep_routes import _wrapper_needed
    assert _wrapper_needed({"session_uuid": "u"}, ["keyc"]).codes == ["wrapper_needed", "launch_profile_needed"]
