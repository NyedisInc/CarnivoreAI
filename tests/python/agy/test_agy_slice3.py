
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from src.config import mcp_launch
from src.config.agent_command import agent_command
from src.config.agents import AgentsConfig
from src.config.launch_profiles import LaunchProfile
from src.core.agy import identity, install, launch

CID = "f2b2d4a0-1111-4222-8333-444455556666"
AGY = {"id": "agy-main", "harness": "custom", "label": "agy", "custom_command": {"script": 'agy "$@"'},
       "agent": {"process": "agy", "rules": "agy", "resume": "agy --conversation {id}"}}
OTHER = {"id": "oc", "harness": "custom", "label": "opencode", "custom_command": {"script": 'opencode "$@"'},
         "agent": {"process": "opencode", "rules": "opencode", "resume": "opencode --session {id}"}}


def _command(profile_id, tmp_path, **kwargs):
    profiles = [LaunchProfile.model_validate(p) for p in (AGY, OTHER)]
    return agent_command(profile_id, agents=AgentsConfig(), resolve_state_dir=lambda: str(tmp_path), disable_alternate_screen=lambda: False,
                         profiles=profiles, explicit=True, **kwargs)


def test_agy_launch_exports_osc_and_the_line_and_keeps_resume(tmp_path):
    plain = _command("agy-main", tmp_path)
    assert plain.startswith("export AGY_CLI_OSC7501=on; ") and launch.LINE_ENV not in plain
    line = "delegate it; it's heavy"
    with_line = _command("agy-main", tmp_path, launch_line=line, extra_args=["--resume", CID], approved_resume_prefixes=["agy"])
    assert "export AGY_CLI_OSC7501=on CARNIVORE_AGY_LAUNCH_LINE=" in with_line and f"--conversation {CID}" in with_line
    assert "--resume" not in with_line and "--mcp-config" not in with_line
    other = _command("oc", tmp_path, launch_line=line)
    assert "AGY_CLI_OSC7501" not in other and launch.LINE_ENV not in other


def test_info_is_agy_reads_the_profile_not_the_name():
    profiles = [SimpleNamespace(id="agy-main", agent=SimpleNamespace(process="agy", rules="agy")),
                SimpleNamespace(id="agy", agent=SimpleNamespace(process="other", rules=None))]
    row = lambda family, kind: SimpleNamespace(agent_family=family, agent_type=kind, session=None)  # noqa: E731
    assert identity.info_is_agy(row("custom", "agy-main"), profiles)
    assert not identity.info_is_agy(row("custom", "agy"), profiles) and not identity.info_is_agy(row("claude", "agy-main"), profiles)


def _home(tmp_path):
    config = tmp_path / ".gemini" / "config"
    (config / "plugins").mkdir(parents=True)
    return config


def test_plugin_install_is_idempotent_and_never_touches_other_files(tmp_path, monkeypatch):
    bridge = tmp_path / "stdio_bridge.py"
    bridge.write_text("#")
    monkeypatch.setattr(mcp_launch, "BRIDGE_SCRIPT", bridge)
    monkeypatch.setattr(mcp_launch, "agy_server_doc", lambda script=bridge: {"command": "python3", "args": [str(script)]})
    config = _home(tmp_path)
    theirs = config / "plugins" / "carnivore"
    theirs.mkdir()
    (theirs / "plugin.json").write_text('{"name": "carnivore"}')
    assert install.install_plugin(config) == "installed"
    ours = config / "plugins" / install.PLUGIN_NAME
    assert json.loads((ours / "mcp_config.json").read_text())["mcpServers"]["carnivore"]["args"] == [str(bridge)]
    assert "CLOUDECODE_HOOK_TOKEN" not in (ours / "mcp_config.json").read_text()
    assert (ours / "rules" / "carnivore.md").is_file() and (ours / "hooks.json").is_file()
    assert install.install_plugin(config) == "unchanged"
    assert (theirs / "plugin.json").read_text() == '{"name": "carnivore"}' and not (config / "config.json").exists()
    (config / "mcp_config.json").write_text(json.dumps({"mcpServers": {"carnivore": {"command": "x"}}}))
    assert install.install_plugin(config) == "installed" and not (ours / "mcp_config.json").exists()
    assert (ours / "plugin.json").is_file()


def test_plugin_install_refuses_a_foreign_folder_and_no_agy(tmp_path):
    config = _home(tmp_path)
    foreign = config / "plugins" / install.PLUGIN_NAME
    foreign.mkdir()
    (foreign / "plugin.json").write_text('{"name": "mine"}')
    assert install.install_plugin(config) == "foreign" and list(foreign.iterdir()) == [foreign / "plugin.json"]
    assert install.install_plugin(tmp_path / "missing") == "no_agy"


def test_install_sets_verbosity_only_when_the_owner_never_did(tmp_path):
    home = tmp_path / ".gemini" / "antigravity-cli"
    home.mkdir(parents=True)
    assert install.install(tmp_path / "s", home) == "installed"
    assert json.loads((home / "settings.json").read_text())["verbosity"] == "medium"
    (home / "settings.json").write_text(json.dumps({"verbosity": "high", "statusLine": {"command": "~/mine.sh"}}))
    assert install.install(tmp_path / "s", home) == "owner_command"
    assert json.loads((home / "settings.json").read_text())["verbosity"] == "high"


def test_launch_line_hook_injects_only_when_the_env_carries_it(monkeypatch, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("hook", install.PLUGIN_SOURCE / "carnivore_launch_line_hook.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    monkeypatch.delenv("CARNIVORE_AGY_LAUNCH_LINE", raising=False)
    hook.main()
    assert capsys.readouterr().out == "{}"
    monkeypatch.setenv("CARNIVORE_AGY_LAUNCH_LINE", "delegate")
    hook.main()
    assert json.loads(capsys.readouterr().out)["injectSteps"][0]["systemMessage"]["systemMessage"] == "delegate"


def _agy_info(**extra):
    return SimpleNamespace(agent_family="custom", agent_type="agy-main", session=SimpleNamespace(agent_type="agy-main", id="1"),
                           tmux_session="t", activity_status="idle", startup_gate="ready", **extra)


def test_family_gates_widen_for_agy_only(monkeypatch):
    from src.core.approvals import dialog_gate
    from src.core.auto_sleep.sleeper import is_sleepable_agent
    from src.core.mcp_health import targets
    from src.core.session_delivery.wake_choice import is_agent_row

    profiles = [SimpleNamespace(id="agy-main", agent=SimpleNamespace(process="agy", rules="agy"))]
    real = identity.row_is_agy
    monkeypatch.setattr(identity, "row_is_agy", lambda row, profiles_=None: real(row, profiles))
    agy, other = _agy_info(), SimpleNamespace(agent_family="custom", agent_type="oc", session=SimpleNamespace(agent_type="oc"))
    for gate in (is_sleepable_agent, is_agent_row, dialog_gate.is_agent_pane):
        assert gate(agy) and not gate(other)
    assert dialog_gate.agy_screen_open("Welcome\nChoose your color scheme:") and not dialog_gate.agy_screen_open("> hello")
    target = targets.monitor_target(None, agy, None)
    assert target is not None and target.family == "agy"
    assert targets.monitor_target(None, other, None) is None
    verdict = asyncio.run(_verdict(agy, "Do you trust the contents of this project?\n  Yes, I trust this folder\n  No, exit"))
    assert verdict == dialog_gate.OPEN


async def _verdict(info, text):
    from src.core.approvals import dialog_gate

    async def get(**_kw):
        return info

    async def capture(_name):
        return text

    state = SimpleNamespace(session_manager=SimpleNamespace(get_session_info=get))
    return await dialog_gate.dialog_verdict(state, "ses_1", capture=capture)


def test_agy_mcp_health_reads_global_and_enabled_plugin_servers(tmp_path):
    from src.core.mcp_health import cached_files
    from src.core.mcp_health.config_agy import agy_servers

    cached_files.reset()
    config = _home(tmp_path)
    (config / "mcp_config.json").write_text(json.dumps({"mcpServers": {"a": {"command": "x", "env": {"T": "secret"}}}}))
    on, off = config / "plugins" / "on", config / "plugins" / "off"
    for d in (on, off):
        d.mkdir()
        (d / "mcp_config.json").write_text(json.dumps({"mcpServers": {d.name: {"url": "https://h/mcp"}}}))
    (config / "config.json").write_text(json.dumps({"plugins": {"off": {"enabled": False}}}))
    specs = {s.name: s for s in agy_servers(str(config))}
    assert set(specs) == {"a", "on"} and specs["on"].transport != "stdio" and specs["a"].command == "x"
    assert "secret" not in repr(specs)


def test_swarm_refuses_an_agy_launch_profile(tmp_path, monkeypatch):
    import pytest

    from src.config import settings as app_settings
    from src.core.swarm import spawn

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"launch_profiles": {"revision": 1, "profiles": [AGY, OTHER]}}))
    monkeypatch.setattr(app_settings, "auth_config_file", str(config))
    with pytest.raises(spawn.SpawnRefused, match="agy"):
        spawn._check_profile("agy-main")
    spawn._check_profile("oc")
