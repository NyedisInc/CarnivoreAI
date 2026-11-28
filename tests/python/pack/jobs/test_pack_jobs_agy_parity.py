
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.config.agent_command import agent_command
from src.config.agents import AgentsConfig
from src.config.launch_profiles import LaunchProfile
from src.core.agy import accounts as agy_accounts, identity, install, transcripts as agy_transcripts
from src.core.opening_prompt import prompt_launch
from src.core.pack.jobs import agent_account, agent_facts, agent_launch, agent_watch, engine_agent, snapshot
from src.core.pack.jobs.agent_types import CAP_AGENT, CAP_AGENT_AGY, AgentSpec
from src.core.pack.jobs.types import AdmitBody, JobError
from src.core.pack.machines import can_block
from src.core.session_token_usage.reader import SessionSubject, read_session_token_usage

AGY_PROFILE = {
    "id": "antigravity",
    "harness": "custom",
    "label": "Antigravity",
    "custom_command": {"script": 'agy --model gemini-4-neon-high "$@"'},
    "agent": {"process": "agy", "rules": "agy", "resume": "agy --conversation {id}"},
}


def _load_precheck_hook():
    spec = importlib.util.spec_from_file_location("agy_precheck_hook", install.PLUGIN_SOURCE / "carnivore_precheck_hook.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agy_precheck_hook_blocks_heavy_command_and_subagent_and_fails_open(monkeypatch, capsys) -> None:
    hook = _load_precheck_hook()
    asked: list[tuple[str, dict]] = []

    def fake_ask(path, payload):
        asked.append((path, payload))
        if path == "precheck":
            return {"decision": "block", "computer": "host-b"}
        if path == "precheck/agent":
            return {"decision": "block", "computer": "host-b"}
        return {"ok": True}

    monkeypatch.setattr(hook, "ask", fake_ask)

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "hookEventName": "PreToolUse", "cwd": "/repo",
        "toolCall": {"id": "t1", "name": "run_command", "args": {"CommandLine": "git status"}},
    })))
    assert hook.main() == 0
    assert json.loads(capsys.readouterr().out) == {"decision": "allow"}
    assert asked == []

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "hookEventName": "PreToolUse", "cwd": "/repo",
        "toolCall": {"id": "t2", "name": "run_command", "args": {"CommandLine": "cd web && npm run build"}},
    })))
    assert hook.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "deny" and "host-b" in out["reason"] and "delegate tool" in out["reason"]
    assert asked[-1] == ("precheck", {"command": "cd web && npm run build", "folder": "/repo/web", "tool_use_id": "t2", "background": False, "timeout_ms": None})

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "hookEventName": "PostToolUse", "cwd": "/repo",
        "toolCall": {"id": "t2", "name": "run_command", "args": {"CommandLine": "npm run build"}},
    })))
    assert hook.main() == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert asked[-1] == ("precheck/finished", {"tool_use_id": "t2"})

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "hookEventName": "PreToolUse", "cwd": "/repo",
        "toolCall": {"id": "t3", "name": "invoke_subagent", "args": {"TypeName": "research", "Prompt": "scan"}},
    })))
    assert hook.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "deny" and "task = the subagent's prompt" in out["reason"]
    assert asked[-1] == ("precheck/agent", {"folder": "/repo", "family": "agy"})

    asked.clear()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "hookEventName": "PreToolUse", "cwd": "/repo",
        "toolCall": {"id": "t4", "name": "invoke_subagent", "args": {"TypeName": "image-generator", "Prompt": "draw"}},
    })))
    assert hook.main() == 0
    assert json.loads(capsys.readouterr().out) == {"decision": "allow"}
    assert asked == []


def test_plugin_install_copies_precheck_hook_and_hooks_json(tmp_path) -> None:
    config = tmp_path / ".gemini" / "config"
    (config / "plugins").mkdir(parents=True)
    assert install.install_plugin(config) == "installed"
    ours = config / "plugins" / install.PLUGIN_NAME
    assert (ours / "carnivore_precheck_hook.py").is_file()
    hooks = json.loads((ours / "hooks.json").read_text(encoding="utf-8"))
    assert "carnivore-agy-delegate" in hooks
    assert hooks["carnivore-agy-delegate"]["PreToolUse"][0]["matcher"] == "run_command|invoke_subagent"
    assert hooks["carnivore-agy-delegate"]["PostToolUse"][0]["matcher"] == "run_command"


def test_wire_can_block_and_snapshot_support_agy() -> None:
    spec = AgentSpec(task="run checks", family="agy", permission_mode="skip_all", model="gemini-4-neon-high")
    assert spec.family == "agy" and spec.permission_mode == "skip_all"
    admit = AdmitBody(job_id="job_0123456789ab", project_uid="proj1234", kind="suite", agent_family="agy")
    assert admit.agent_family == "agy"
    with pytest.raises(ValidationError):
        AgentSpec(task="x", family="agy", permission_mode="bypassPermissions")
    with pytest.raises(ValidationError):
        AgentSpec(task="x", family="agy", permission_mode="default", agent_type="rev", definition_json='{"prompt":"x"}')
    assert "agy" in can_block.TOOL_NAMES
    assert ".agents/hooks.json" in snapshot.HARNESS_CONFIG_PATHS


def test_agent_view_filters_agy_peers_by_capability_and_tool() -> None:
    from src.core.pack.jobs.place import PlaceView

    p_ok = SimpleNamespace(install_id="a", snapshot={"can": {"tools": {"agy": True}}})
    p_no_bin = SimpleNamespace(install_id="b", snapshot={"can": {"tools": {"agy": False}}})
    p_old = SimpleNamespace(install_id="c", snapshot={"can": {"tools": {"agy": True}}})
    view = PlaceView(
        self_input=SimpleNamespace(install_id="self"),
        peers=[p_ok, p_no_bin, p_old],
        caps={"a": [CAP_AGENT, CAP_AGENT_AGY], "b": [CAP_AGENT, CAP_AGENT_AGY], "c": [CAP_AGENT]},
    )
    filtered = engine_agent.AgentMixin._agent_view(view, family="agy")
    assert [p.install_id for p in filtered.peers] == ["a"]
    claude_view = engine_agent.AgentMixin._agent_view(view, family="claude")
    assert [p.install_id for p in claude_view.peers] == ["a", "b", "c"]


def test_agy_caller_facts_and_target_account(tmp_path, monkeypatch) -> None:
    profiles = [LaunchProfile.model_validate(AGY_PROFILE)]
    assert identity.agy_profile_id(profiles) == "antigravity"
    info = SimpleNamespace(
        agent_family="custom", agent_type="antigravity", tmux_session="t1", session_uuid="u1",
        claude_session_uuid="11111111-2222-3333-4444-555555555555", running_model=None,
        launched_with={"permissions": "skip_all"},
        session=SimpleNamespace(id="ses_1", agent_type="antigravity"),
    )
    app = SimpleNamespace(state=SimpleNamespace(session_manager=SimpleNamespace()))

    async def fake_info(_sm, _caller):
        return info

    monkeypatch.setattr(agent_facts, "info_for_caller", fake_info)
    monkeypatch.setattr(identity, "info_is_agy", lambda _i, _p=None: True)
    from src.core.agy import state as agy_state
    monkeypatch.setattr(agy_state, "state_for_conversation", lambda _sd, _cid: {
        "email": "Alice@Example.com", "model": {"id": "gemini-4-neon-high"},
    })
    facts = asyncio.run(agent_facts.caller_launch_facts(app, "u1"))
    assert facts.family == "agy"
    assert facts.permission_mode == "skip_all"
    assert facts.model == "gemini-4-neon-high"
    assert facts.account_identity == "alice@example.com"
    assert facts.account_key == "agy-alice-example-com"

    monkeypatch.setattr(agy_accounts, "read_live", lambda: None)
    with pytest.raises(JobError) as exc:
        agent_account.resolve_target_account("agy", None, None, tmp_path / "missing.json")
    assert exc.value.code == "account_not_usable"

    monkeypatch.setattr(agy_accounts, "read_live", lambda: "opaque-blob")
    pick = agent_account.resolve_target_account("agy", "agy-alice-example-com", None, tmp_path / "missing.json", "alice@example.com")
    assert pick.how == "fallback" and pick.account_id is None


def test_agy_launch_opening_prompt_and_safe_args(tmp_path) -> None:
    spec = AgentSpec(task="check build", family="agy", permission_mode="skip_all", model="gemini-4-neon-high")
    plan = agent_launch.build_launch(spec, tmp_path, "job_0123456789ab", agent_account.AccountPick(None))
    assert plan.agent_type == "agy"
    assert plan.extra_args == ["--dangerously-skip-permissions"]

    profiles = [LaunchProfile.model_validate(AGY_PROFILE)]
    fake_settings = SimpleNamespace(
        load_auth_config=lambda: SimpleNamespace(agents=SimpleNamespace(wrappers=[])),
        get_launch_profiles=lambda: profiles,
    )
    resolved, prompt_args = prompt_launch(fake_settings, agent_type="antigravity", project_name=None, opening_prompt=agent_launch.OPENING_PROMPT)
    assert resolved == "antigravity"
    assert prompt_args == ["--prompt-interactive", agent_launch.OPENING_PROMPT]

    cmd = agent_command(
        "antigravity", agents=AgentsConfig(), resolve_state_dir=lambda: str(tmp_path), disable_alternate_screen=lambda: False,
        profiles=profiles, explicit=True,
        extra_args=["--name", "bad", "--dangerously-skip-permissions", "--model", "gemini-4-neon-high", "--prompt-interactive", "do the thing"],
    )
    assert "--dangerously-skip-permissions" in cmd and "--prompt-interactive" in cmd and "do the thing" in cmd
    assert "--name" not in cmd


def test_agy_watch_transcript_and_usage_reader(tmp_path, monkeypatch) -> None:
    cid = "11111111-2222-3333-4444-555555555555"
    log_dir = tmp_path / "brain" / cid / ".system_generated" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "transcript.jsonl").write_text(
        json.dumps({"type": "USER_INPUT", "content": "hi", "created_at": "2026-11-25T10:00:00Z"}) + "\n"
        + json.dumps({"type": "PLANNER_RESPONSE", "content": "all green", "created_at": "2026-11-25T10:05:00Z"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(agy_transcripts, "AGY_HOME", tmp_path)
    got = agent_watch.read_transcript("agy", cid, None, None)
    assert got.text == "all green" and got.last_at is not None

    from src.config import settings as app_settings
    from src.core.agy import state as agy_state
    state_dir = tmp_path / "state"
    agy_dir = state_dir / agy_state.STATE_FOLDER
    agy_dir.mkdir(parents=True)
    (agy_dir / "42.json").write_text(json.dumps({
        "conversation_id": cid, "written_at": 100.0,
        "model": {"id": "gemini-4-neon-high", "display_name": "Gemini 4 Neon (High)"},
        "context_window": {"total_input_tokens": 500, "total_output_tokens": 200, "context_window_size": 1000000, "used_percentage": 1.0},
        "cost": {"total_usd": 0.12},
    }), encoding="utf-8")
    monkeypatch.setattr(type(app_settings), "get_state_dir", lambda _self: state_dir)
    usage = read_session_token_usage(SessionSubject("agy", cid, None))
    assert usage.state == "ok" and usage.family == "agy" and usage.input_tokens == 500 and usage.output_tokens == 200
