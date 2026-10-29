
import asyncio
import os
import shlex
import subprocess
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from src.config.byoai import ConnectionConfig
from src.config.launch_profiles import LaunchProfile, SecretRow
from src.core.byoai.contracts import Connection
from src.core.byoai.contracts import to_connection
from src.core.byoai.keys import KeyStore
from src.core.launch_profiles.endpoints import (
    ConnectionMissing, EndpointRefused, OriginMismatch, UnsupportedEndpoint, codex_key_variable, endpoint_launch,
)
from src.core.launch_profiles.fold_local_host import fold_local_host
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch
from src.core.launch_profiles.secrets import KeyUnavailable, PreviewRefused, materialize, staging_name
from tests.helpers.scripted_model import rig as rig_module
from tests.helpers.scripted_model.anthropic_sse import RIG_MODEL

KEY = "sk-fake-0123456789abcdef"


class FakeBackend:

    def __init__(self, values):
        self.values = dict(values)

    def read(self, service, account):
        return self.values.get(account)


def _keys(**values):
    return KeyStore(backend=FakeBackend(values))


def _conn(cid, preset, url, *, key=True, hint="cdef", **kw):
    return Connection(id=cid, preset=preset, label=kw.pop("label", cid), base_url=url,
                      key_host=(kw.pop("key_host", None) or ("/".join(url.split("/")[:3]))) if key else None,
                      key_hint=hint if key else "", **kw)


OPENROUTER = _conn("or", "openrouter", "https://openrouter.ai/api/v1")
ANTHROPIC = _conn("anth", "anthropic", "https://api.anthropic.com")
LMSTUDIO = _conn("lmstudio", "lmstudio", "http://192.168.1.50:1234/v1", key=False)


def _profile(harness, cid, model_mode="fixed", model="m-1", **kw):
    fields = {"id": f"{harness}-ep", "harness": harness, "label": "ep", "endpoint": {"mode": "connection", "connection_id": cid},
              "model": {"mode": model_mode, **({"value": model} if model_mode == "fixed" else {})}, **kw}
    return LaunchProfile.model_validate(fields)


def _plan(harness, conn, purpose="pane", **kw):
    request = LaunchRequest(profiles=(_profile(harness, conn.id, **kw),), agent_type=f"{harness}-ep", connections=(conn,),
                            app_args=("--resume", "u-1"))
    return resolve_launch(request, purpose)


def _tiers(model):
    return {f"ANTHROPIC_DEFAULT_{t}_MODEL": model for t in ("OPUS", "SONNET", "HAIKU")} | {"CLAUDE_CODE_SUBAGENT_MODEL": model}


def test_claude_goldens():
    p = _plan("claude", OPENROUTER)
    assert dict(p.env_set) == {"ANTHROPIC_BASE_URL": "https://openrouter.ai/api", "ANTHROPIC_API_KEY": "", **_tiers("m-1")}
    assert p.secret_refs == (("ANTHROPIC_AUTH_TOKEN", "or"),)
    assert {"ANTHROPIC_MODEL", "OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"} <= set(p.env_unset)
    assert not {"ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"} & set(p.env_unset)
    assert " --model m-1 " in p.command + " " and p.command.endswith("_ --resume u-1")
    assert (p.display.endpoint, p.display.key_hint, p.display.model) == ("or", "cdef", "m-1")
    a = _plan("claude", ANTHROPIC)
    assert dict(a.env_set) == {"ANTHROPIC_BASE_URL": "https://api.anthropic.com", **_tiers("m-1")}
    assert a.secret_refs == (("ANTHROPIC_API_KEY", "anth"),) and "ANTHROPIC_AUTH_TOKEN" in a.env_unset
    lm = resolve_launch(LaunchRequest(
        profiles=(_profile("claude", "lmstudio", "ask"),), agent_type="claude-ep", connections=(LMSTUDIO,), model="qwen3"))
    assert dict(lm.env_set) == {"ANTHROPIC_BASE_URL": "http://192.168.1.50:1234", "ANTHROPIC_API_KEY": "",
                                "ANTHROPIC_AUTH_TOKEN": "carnivore", **_tiers("qwen3")}
    assert lm.secret_refs == () and lm.display.key_hint == "" and lm.display.model == "qwen3"


def test_codex_golden_keeps_v1_and_key_rides_in_env():
    p = _plan("codex", OPENROUTER)
    inner = shlex.split(p.command)[2]
    flags = shlex.split(inner.rsplit("; codex ", 1)[1])
    assert flags[:2] == ["$@", "-c"] and flags[-2:] == ["-m", "m-1"]
    for setting in ('model_provider="carnivore-or"', 'model_providers.carnivore-or.base_url="https://openrouter.ai/api/v1"',
                    'model_providers.carnivore-or.env_key="CARNIVORE_OR_API_KEY"', 'model_providers.carnivore-or.wire_api="responses"'):
        assert setting in flags
    assert p.secret_refs == (("CARNIVORE_OR_API_KEY", "or"),) and p.env_set == ()
    assert KEY not in p.command and codex_key_variable("or") == "CARNIVORE_OR_API_KEY"
    ep = endpoint_launch("codex", LMSTUDIO, "q")
    assert ep.secret_refs == () and not any("env_key" in f for f in ep.flags)


def test_refusals_and_secret_name_rule():
    with pytest.raises(OriginMismatch):
        endpoint_launch("claude", _conn("x", "openrouter", "https://openrouter.ai/api/v1", key_host="https://evil.example"), "m")
    with pytest.raises(ConnectionMissing):
        resolve_launch(LaunchRequest(profiles=(_profile("claude", "gone"),), agent_type="claude-ep"))
    with pytest.raises(UnsupportedEndpoint):
        endpoint_launch("shell", OPENROUTER, "m")
    with pytest.raises(UnsupportedEndpoint):
        endpoint_launch("codex", _conn("o", "ollama", "http://127.0.0.1:11434/v1", key=False), "m")
    with pytest.raises(EndpointRefused):
        resolve_launch(LaunchRequest(profiles=(_profile("claude", "lmstudio", "default"),), agent_type="claude-ep", connections=(LMSTUDIO,)))
    with pytest.raises(EndpointRefused):
        endpoint_launch("claude", _conn("or", "openrouter", "https://openrouter.ai/api/v1", key=False), "m")
    with pytest.raises(ValidationError):
        SecretRow.model_validate({"name": "MYAPI" + "KEY", "keychain_ref": "or"})
    SecretRow.model_validate({"name": "MY_API_" + "KEY", "keychain_ref": "or"})


def test_materialize_rules_and_no_value_in_command_or_logs():
    plan = _plan("claude", OPENROUTER)
    with pytest.raises(PreviewRefused):
        asyncio.run(materialize(_plan("claude", OPENROUTER, purpose="preview"), keys=_keys(**{"or": KEY})))
    with capture_logs() as logs:
        staged = asyncio.run(materialize(plan, keys=_keys(**{"or": KEY})))
    assert staged == {staging_name(0): KEY} and staging_name(0) == "CARNIVORE_LAUNCH_SECRET_0"
    from src.core.debug_trace import is_secret_name
    assert is_secret_name(staging_name(0))
    assert KEY not in plan.command and KEY not in repr(plan) and KEY not in repr(logs)
    assert 'export ANTHROPIC_AUTH_TOKEN="$CARNIVORE_LAUNCH_SECRET_0"; unset CARNIVORE_LAUNCH_SECRET_0' in plan.command
    for locked in ({}, {"or": ""}):
        with pytest.raises(KeyUnavailable) as err:
            asyncio.run(materialize(plan, keys=_keys(**locked)))
        assert KEY not in str(err.value)


def test_staged_secret_is_exported_after_the_rc_in_a_real_shell(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text("export ANTHROPIC_AUTH_TOKEN=from-the-rc\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dump = tmp_path / "dump"
    stub = bin_dir / "claude"
    stub.write_text(f'#!/bin/sh\nenv > {dump}\necho "ARGV $*" >> {dump}\n')
    stub.chmod(0o755)
    plan = _plan("claude", OPENROUTER)
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin", "ZDOTDIR": str(home),
           "ANTHROPIC_MODEL": "stale", **dict(plan.env_set), staging_name(0): KEY}
    for name in plan.env_unset:
        env.pop(name, None)
    subprocess.run(["/bin/zsh", "-c", plan.command], env=env, check=True, timeout=30)
    seen = dict(line.split("=", 1) for line in dump.read_text().splitlines() if "=" in line and not line.startswith("ARGV"))
    assert seen["ANTHROPIC_AUTH_TOKEN"] == KEY and staging_name(0) not in seen and "ANTHROPIC_MODEL" not in seen
    assert seen["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api" and "ARGV --model m-1 --resume u-1" in dump.read_text()


def test_rig_is_expressible_as_endpoint_profiles(tmp_path):
    url = "http://127.0.0.1:43999"
    conn = _conn("rig", "custom", f"{url}/v1", hint="", key_host=url, options={"capabilities": ["chat"]})
    claude = endpoint_launch("claude", conn, RIG_MODEL)
    script = rig_module.claude_script(url, tmp_path / "cfg")
    rig_env = dict(t.split("=", 1) for t in shlex.split(script.split(" env ", 1)[1].split(" claude ", 1)[0]) if "=" in t)
    ours = dict(claude.env_set)
    for name in ("ANTHROPIC_BASE_URL", "CLAUDE_CODE_SUBAGENT_MODEL", *(f"ANTHROPIC_DEFAULT_{t}_MODEL" for t in ("OPUS", "SONNET", "HAIKU"))):
        assert ours[name] == rig_env[name]
    assert rig_env["ANTHROPIC_AUTH_TOKEN"] == "rig" and "-u ANTHROPIC_API_KEY" in script and ours["ANTHROPIC_API_KEY"] == ""
    home = tmp_path / "codex"
    rig_module.seed_codex_home(home, url, tmp_path)
    provider = tomllib.loads((home / "config.toml").read_text())["model_providers"]["rig"]
    codex = endpoint_launch("codex", _conn("rig", "custom", f"{url}/v1", hint="", key_host=url, options={"capabilities": ["chat"]}), RIG_MODEL)
    settings = dict(f.split("=", 1) for f in codex.flags if f != "-c")
    pid = "carnivore-rig"
    assert tomllib.loads(f"v = {settings[f'model_providers.{pid}.base_url']}")["v"] == provider["base_url"]
    assert tomllib.loads(f"v = {settings[f'model_providers.{pid}.wire_api']}")["v"] == provider["wire_api"]
    assert codex.secret_refs == (("CARNIVORE_RIG_API_KEY", "rig"),) and provider["env_key"] == "RIG_KEY"


def test_v8_folds_local_host_once():
    data = {"config_version": 7, "providers": {"local_host": "10.0.0.5:1234", "models": ["a/b"]}, "byoai": {"revision": 3, "connections": []}}
    once = fold_local_host(data)
    assert data["byoai"]["connections"] == [] and once["providers"] == data["providers"]
    (c,) = once["byoai"]["connections"]
    assert (c["id"], c["preset"], c["base_url"], c["key_host"]) == ("lmstudio", "lmstudio", "http://10.0.0.5:1234/v1", None)
    assert once["byoai"]["revision"] == 4 and fold_local_host(once) is once
    assert fold_local_host({"providers": {"local_host": ""}}) == {"providers": {"local_host": ""}}
    assert fold_local_host({}) == {}
    p = resolve_launch(LaunchRequest(profiles=(_profile("claude", "lmstudio"),), agent_type="claude-ep",
                                     connections=(to_connection(ConnectionConfig(**c)),)))
    assert dict(p.env_set)["ANTHROPIC_BASE_URL"] == "http://10.0.0.5:1234"
