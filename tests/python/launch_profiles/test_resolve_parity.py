
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.config.agents import AgentsConfig
from src.config.launch_profiles import LaunchProfile
from src.core.agent_wrappers import AgentWrapper, wrapper_scripts_dir
from src.core.launch_profiles.endpoints import ConnectionMissing
from src.core.launch_profiles.permissions import PERMISSION_FLAGS, UnsupportedPosture, permission_flags
from src.core.launch_profiles.resolve import (
    LaunchProfileNotFound, LaunchRequest, _transparent_codex_yolo, pick_profile, resolve_launch,
)
from src.core.launch_profiles.seed_from_wrappers import seed_launch_profiles
from tests.python.launch_profiles.legacy_render import legacy_agent_command as agent_command
from tests.python.launch_profiles.test_config_migration_v7 import _config

FIXTURES = Path(__file__).parent / "fixtures"
APP_ARGS = ("--resume", "11111111-2222-3333-4444-555555555555", "--name", "my proj",
            "--mcp-config={\"mcpServers\":{}}", "open the 'prompt' $HOME")
AGENT_TYPES = ["claude", "keyc", "clxor", "codex-yolo", "hermes-default", "openclaw-default", "local-default",
               "shell-default", "codex", "shell", "hermes", "openclaw", "local", "no-such-legacy-value", None]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    data = _config()
    seeded = seed_launch_profiles(data)
    profiles = tuple(LaunchProfile.model_validate(p) for p in seeded["launch_profiles"]["profiles"])
    agents = AgentsConfig(wrappers=[AgentWrapper(**w) for w in data["agents"]["wrappers"]])
    state = tmp_path / "state"
    return agents, profiles, state


def _today(world, agent_type, model, args, alt):
    agents, _, state = world
    try:
        return agent_command(agent_type, agents=agents, resolve_state_dir=lambda: str(state),
                             disable_alternate_screen=lambda: alt, model=model, extra_args=list(args))
    except ValueError:
        return "ValueError"


def _mine(world, agent_type, model, args, alt):
    _, profiles, state = world
    request = LaunchRequest(profiles=profiles, agent_type=agent_type, model=model, app_args=tuple(args),
                            scripts_dir=wrapper_scripts_dir(str(state)), disable_alternate_screen=alt)
    try:
        plan = resolve_launch(request, "pane")
    except ValueError:
        return None, "ValueError"
    return plan, plan.command


@pytest.mark.parametrize("agent_type", AGENT_TYPES)
@pytest.mark.parametrize("model", [None, "vendor/some-model"])
@pytest.mark.parametrize("args", [(), APP_ARGS])
@pytest.mark.parametrize("alt", [False, True])
def test_command_matches_todays_render(world, agent_type, model, args, alt):
    plan, command = _mine(world, agent_type, model, args, alt)
    today = _today(world, agent_type, model, args, alt)
    if _transparent_codex_yolo(pick_profile(LaunchRequest(profiles=world[1], agent_type=agent_type))):
        assert plan is not None and plan.script_file is not None
        return
    if plan is None or plan.script_file is None:
        assert (plan is None) == (today == "ValueError")
        return
    assert command == today
    if True:
        written = Path(plan.script_file.path)
        assert written.read_text() == plan.script_file.content
        assert plan.display.label and len(plan.digest) == 64 and plan.purpose == "pane"


def _stubs(tmp_path):
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    (home / ".zshrc").write_text("export STUB_RC_LOADED=1\n")
    body = '#!/bin/sh\nexec "$PYBIN" -c "import json, os, sys; ' \
           "open(os.environ['DUMP'], 'w').write(json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ)}))\" \"$@\"\n"
    for name in ("claude", "codex", "stubsh"):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    return home, bin_dir


def _run(command, tmp_path, tag):
    home, bin_dir = _stubs(tmp_path) if not (tmp_path / "home").exists() else (tmp_path / "home", tmp_path / "bin")
    dump = tmp_path / f"{tag}.json"
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "SHELL": str(bin_dir / "stubsh"),
           "DUMP": str(dump), "PYBIN": sys.executable}
    done = subprocess.run(command, shell=True, env=env, capture_output=True, text=True, timeout=30)
    assert dump.exists(), f"the stub never ran: rc={done.returncode} stderr={done.stderr[:300]}"
    out = json.loads(dump.read_text())
    for noise in ("_", "SHLVL"):
        out["env"].pop(noise, None)
    out["env"].pop("DUMP")
    out["env"].pop("PYBIN")
    return out


@pytest.mark.parametrize("agent_type", ["claude", "shell-default"])
@pytest.mark.parametrize("args", [(), APP_ARGS])
@pytest.mark.parametrize("alt", [False, True])
def test_structured_seed_runs_with_the_same_argv_and_env(world, tmp_path, agent_type, args, alt):
    _, command = _mine(world, agent_type, None, args, alt)
    today = _today(world, agent_type, None, args, alt)
    mine_run = _run(command, tmp_path, "mine")
    today_run = _run(today, tmp_path, "today")
    assert mine_run["argv"] == today_run["argv"]
    assert mine_run["env"] == today_run["env"], {k: (mine_run["env"].get(k), today_run["env"].get(k))
                                                for k in mine_run["env"].keys() | today_run["env"].keys()
                                                if mine_run["env"].get(k) != today_run["env"].get(k)}
    assert mine_run["argv"][-len(args):] == list(args) if args else True
    if agent_type == "claude":
        assert mine_run["argv"][0] == "--dangerously-skip-permissions" and mine_run["env"]["STUB_RC_LOADED"] == "1"
    else:
        assert mine_run["argv"][0] == "-i" and "STUB_RC_LOADED" not in mine_run["env"]


def test_structured_codex_and_claude_argv(world, tmp_path):
    _, _, state = world
    codex = LaunchProfile.model_validate({"id": "cx", "harness": "codex", "label": "cx", "permissions": "ask",
                                          "flags": ["-c", "model_reasoning_effort=high"], "model": {"mode": "ask"}})
    claude = LaunchProfile.model_validate({"id": "cl", "harness": "claude", "label": "cl", "permissions": "accept_edits",
                                          "model": {"mode": "fixed", "value": "opus"}, "before_launch": "export BL=1"})
    for profile, expect in ((codex, ["resume", "u1", "--ask-for-approval", "on-request", "-c", "model_reasoning_effort=high", "-m", "gpt-x"]),
                            (claude, ["--permission-mode", "acceptEdits", "--model", "opus", "resume", "u1"])):
        plan = resolve_launch(LaunchRequest(profiles=(profile,), agent_type=profile.id, model="gpt-x",
                                            app_args=("resume", "u1"), scripts_dir=state), "preview")
        out = _run(plan.command, tmp_path, profile.id)
        assert out["argv"] == expect
        assert plan.script_file is None and plan.argv_tail == ("resume", "u1")
    assert out["env"]["BL"] == "1"


def test_pick_and_guard_rules(world):
    _, profiles, state = world
    base = dict(profiles=profiles, scripts_dir=state)
    assert resolve_launch(LaunchRequest(agent_type="shell", **base)).display.label == "shell-default"
    assert resolve_launch(LaunchRequest(agent_type="gone", **base)).display.label == "keyc"
    assert resolve_launch(LaunchRequest(profiles=(), agent_type="codex", scripts_dir=state)).display.harness == "codex"
    with pytest.raises(LaunchProfileNotFound) as err:
        resolve_launch(LaunchRequest(agent_type="gone", explicit=True, **base))
    assert err.value.codes == ("wrapper_needed", "launch_profile_needed")
    conn = LaunchProfile.model_validate({"id": "or", "harness": "claude", "label": "or",
                                         "endpoint": {"mode": "connection", "connection_id": "c1"}})
    with pytest.raises(ConnectionMissing):
        resolve_launch(LaunchRequest(profiles=(conn,), agent_type="or", scripts_dir=state))
    for model, mode in ((None, "default"), ("asked", "ask")):
        p = LaunchProfile.model_validate({"id": "m", "harness": "claude", "label": "m", "model": {"mode": mode}})
        assert resolve_launch(LaunchRequest(profiles=(p,), agent_type="m", model=model, scripts_dir=state)).display.model == (model or mode)
    with pytest.raises(ValueError):
        resolve_launch(LaunchRequest(profiles=profiles, agent_type="x", scripts_dir=state), "bogus")


def test_permission_table_matches_the_help_fixtures():
    claude_help = (FIXTURES / "claude_help_permissions.txt").read_text()
    codex_help = (FIXTURES / "codex_help_permissions.txt").read_text()
    for posture, tokens in PERMISSION_FLAGS["claude"].items():
        for token in tokens:
            assert token in claude_help, (posture, token)
    assert permission_flags("claude", "harness_default") == permission_flags("codex", "harness_default") == ()
    assert "--dangerously-bypass-approvals-and-sandbox" in codex_help
    assert "--ask-for-approval" in codex_help and "on-request" in codex_help
    assert permission_flags("codex", "skip_all") == ("--yolo",)
    for harness, posture in (("codex", "accept_edits"), ("shell", "skip_all"), ("shell", "ask"), ("hermes", "ask")):
        with pytest.raises(UnsupportedPosture):
            permission_flags(harness, posture)
