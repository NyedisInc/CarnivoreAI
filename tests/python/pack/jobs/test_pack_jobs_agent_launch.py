
from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.core.pack.jobs import agent_account, agent_launch, paths
from src.core.pack.jobs.agent_account import AccountPick, resolve_target_account
from src.core.pack.jobs.agent_launch import OPENING_PROMPT, build_launch, write_task_file
from src.core.pack.jobs.agent_types import AgentSpec
from src.core.pack.jobs.types import JobError
from src.models.blueprints import check_opening_prompt

JOB = "job_0123456789ab"
SECRET_TASK = "SECRETTASK-rm -rf $(whoami) `id`"
FAKE = Path(__file__).with_name("pack_jobs_fake_agent.py")


def _spec(**over) -> AgentSpec:
    base = {"task": SECRET_TASK, "family": "claude", "permission_mode": "acceptEdits"}
    base.update(over)
    return AgentSpec(**base)


def _plan(spec: AgentSpec, pick: AccountPick = None, tmp: Path = Path("/x")):
    return build_launch(spec, tmp, JOB, pick or AccountPick(None, {"CLAUDE_CONFIG_DIR": "/p"}, "k", "relay"))


def test_claude_argv_postures_and_prompt():
    ask = _plan(_spec(permission_mode="default"))
    assert ask.extra_args == ["--permission-mode", "manual"] and ask.agent_type == "claude"
    assert _plan(_spec(permission_mode="plan")).extra_args == ["--permission-mode", "manual"]
    assert _plan(_spec(permission_mode="acceptEdits")).extra_args == ["--permission-mode", "acceptEdits"]
    assert _plan(_spec(permission_mode="bypassPermissions")).extra_args == ["--dangerously-skip-permissions"]
    assert _plan(_spec(permission_mode="dontAsk")).extra_args == ["--permission-mode", "dontAsk"]
    assert _plan(_spec(permission_mode="auto")).extra_args == ["--permission-mode", "auto"]
    assert ask.opening_prompt == OPENING_PROMPT and check_opening_prompt(OPENING_PROMPT) == OPENING_PROMPT


def test_definition_is_one_argv_element_and_model_precedence():
    definition = json.dumps({"description": "d", "prompt": "be careful; $(x)", "model": "opus"})
    plan = _plan(_spec(agent_type="reviewer", definition_json=definition, model="sonnet"))
    i = plan.extra_args.index("--agents")
    assert json.loads(plan.extra_args[i + 1]) == {"reviewer": json.loads(definition)}
    assert plan.extra_args[i + 2:i + 4] == ["--agent", "reviewer"] and plan.agent_name == "reviewer"
    assert plan.model == "opus"
    assert _plan(_spec(agent_type="reviewer", definition_json=json.dumps({"prompt": "p"}), model="sonnet")).model == "sonnet"
    none = _plan(_spec(model="sonnet", agent_type="reviewer"))
    assert "--agents" not in none.extra_args and "--agent" not in none.extra_args and none.model == "sonnet"


def test_definition_revalidated_on_target():
    spec = _spec(agent_type="r", definition_json=json.dumps({"prompt": "p"}))
    object.__setattr__(spec, "definition_json", json.dumps({"prompt": "p", "hooks": {}}))
    with pytest.raises(JobError) as err:
        _plan(spec)
    assert err.value.code == "bad_launch"
    spec = _spec(agent_type="r", definition_json=json.dumps({"prompt": "p"}))
    object.__setattr__(spec, "model", "a b")
    with pytest.raises(JobError):
        _plan(spec)
    with pytest.raises(JobError):
        build_launch(_spec(), Path("/x"), "job_../etc", AccountPick(None))


def test_codex_argv():
    codex = {"family": "codex"}
    assert _plan(_spec(permission_mode="skip_all", **codex)).extra_args == ["--yolo"]
    assert _plan(_spec(permission_mode="ask", **codex)).extra_args == ["--ask-for-approval", "on-request"]
    with pytest.raises(ValueError):
        _spec(permission_mode="unknown", **codex)
    assert _plan(_spec(permission_mode="skip_all", **codex)).agent_type == "codex"


def test_task_text_never_in_argv_or_env_and_push_block_shared():
    pick = AccountPick("acct", {"CLAUDE_CONFIG_DIR": "/p"}, "acct", "same")
    plan = _plan(_spec(agent_type="r", definition_json=json.dumps({"prompt": "p"})), pick)
    blob = json.dumps([plan.extra_args, plan.extra_env, plan.opening_prompt, plan.model, plan.agent_type])
    assert "SECRETTASK" not in blob
    assert plan.account_id == "acct" and plan.extra_env["CARNIVORE_JOB_ID"] == JOB and plan.extra_env["CLAUDE_CONFIG_DIR"] == "/p"
    assert all(plan.extra_env[k] == v for k, v in paths.push_block_env().items())


def test_task_file_private_and_excluded(tmp_path):
    slot = tmp_path / "slot"
    slot.mkdir()
    subprocess.run(["git", "init", "-q", str(slot)], check=True)
    target = write_task_file(slot, _spec())
    assert target == slot / ".carnivore-job" / "task.md" and target.read_text() == SECRET_TASK
    assert stat.S_IMODE(target.stat().st_mode) == 0o600 and stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    status = subprocess.run(["git", "-C", str(slot), "status", "--porcelain", "-uall"], capture_output=True, text=True).stdout
    assert ".carnivore-job" not in status
    write_task_file(slot, _spec(task="again"))
    assert (slot / ".git" / "info" / "exclude").read_text().count("/.carnivore-job/") == 1 and target.read_text() == "again"


def test_task_file_refuses_planted_symlinks(tmp_path):
    slot = tmp_path / "slot"
    slot.mkdir()
    subprocess.run(["git", "init", "-q", str(slot)], check=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (slot / ".carnivore-job").symlink_to(outside)
    with pytest.raises(JobError) as err:
        write_task_file(slot, _spec())
    assert err.value.code == "bad_slot" and not list(outside.iterdir())
    (slot / ".carnivore-job").unlink()
    (slot / ".carnivore-job").mkdir()
    (outside / "victim").write_text("keep")
    (slot / ".carnivore-job" / "task.md").symlink_to(outside / "victim")
    write_task_file(slot, _spec())
    assert (outside / "victim").read_text() == "keep" and not (slot / ".carnivore-job" / "task.md").is_symlink()


def _cfg(tmp_path) -> Path:
    return tmp_path / "config.json"


def test_claude_relay_beats_active(monkeypatch, tmp_path):
    calls = []

    def launch_for(key, sender, cfg):
        calls.append((key, sender))
        return {"account_id": None, "extra_env": {"CLAUDE_CONFIG_DIR": "/relay"}} if key == "relayacct" else None

    monkeypatch.setattr(agent_account.move_account, "launch_for", launch_for)
    pick = resolve_target_account("claude", "relayacct", "iid-a", _cfg(tmp_path))
    assert (pick.how, pick.extra_env, pick.label) == ("relay", {"CLAUDE_CONFIG_DIR": "/relay"}, "relayacct") and calls == [("relayacct", "iid-a")]


def test_claude_same_local_login(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_account.move_account, "launch_for", lambda k, s, c: {"account_id": k, "extra_env": None})
    pick = resolve_target_account("claude", "work", "iid-a", _cfg(tmp_path))
    assert (pick.how, pick.account_id, pick.extra_env) == ("same", "work", {})


def test_claude_fallback_marked_and_refusal(monkeypatch, tmp_path):
    class Active:
        account_id = "mine"

    monkeypatch.setattr(agent_account, "effective_active", lambda *a: Active())
    monkeypatch.setattr(agent_account.session_pin, "all_accounts", lambda c: [])
    monkeypatch.setattr(agent_account.store, "read_switch", lambda c: None)
    monkeypatch.setattr(agent_account.move_account, "launch_for",
                        lambda k, s, c: {"account_id": "mine", "extra_env": None} if k == "mine" else None)
    pick = resolve_target_account("claude", "theirs", "iid-a", _cfg(tmp_path))
    assert (pick.how, pick.account_id, pick.label) == ("fallback", "mine", "mine")
    monkeypatch.setattr(agent_account.move_account, "launch_for", lambda k, s, c: None)
    with pytest.raises(JobError) as err:
        resolve_target_account("claude", "theirs", "iid-a", _cfg(tmp_path))
    assert err.value.code == "account_not_usable" and err.value.status == 409


def test_codex_relay_fallback_and_refusal(monkeypatch, tmp_path):
    home = tmp_path / "relay-codex"
    home.mkdir()
    monkeypatch.setattr(agent_account.codex_target, "codex_relay_profile_dir", lambda k, s: str(home))
    pick = resolve_target_account("codex", "work", "iid-a", _cfg(tmp_path))
    assert pick.how == "relay" and pick.extra_env["CODEX_HOME"] == str(home) and "CODEX_REFRESH_TOKEN_URL_OVERRIDE" in pick.extra_env
    monkeypatch.setattr(agent_account.codex_target, "codex_relay_profile_dir", lambda k, s: str(tmp_path / "none"))
    monkeypatch.setattr(agent_account.codex_target, "find_codex_relay_profile", lambda k: None)
    monkeypatch.setattr(agent_account.session_pin, "all_accounts", lambda c: [])
    monkeypatch.setattr(agent_account.codex_follow, "follow_active_account", lambda c: "codex-1")
    pick = resolve_target_account("codex", "work", "iid-a", _cfg(tmp_path))
    assert (pick.how, pick.account_id, pick.extra_env) == ("fallback", "codex-1", {})

    def refuse(c):
        raise agent_account.codex_follow.CodexAccountRefused("none", [])

    monkeypatch.setattr(agent_account.codex_follow, "follow_active_account", refuse)
    with pytest.raises(JobError) as err:
        resolve_target_account("codex", None, None, _cfg(tmp_path))
    assert err.value.code == "account_not_usable"


def test_resolve_refuses_bad_inputs(tmp_path):
    for family, key in (("gemini", None), ("claude", "Bad Key"), ("codex", "x;y")):
        with pytest.raises(JobError):
            resolve_target_account(family, key, None, _cfg(tmp_path))


def test_definition_too_large_for_one_tmux_command():
    with pytest.raises(ValueError):
        _spec(agent_type="big", definition_json=json.dumps({"prompt": "x" * 9000}))
    with pytest.raises(JobError) as err:
        _plan(_spec(agent_type="big", definition_json=json.dumps({"prompt": "'" * 3000})))
    assert err.value.code == "definition_too_large"


def test_hooks_signatures():
    import inspect

    create, stop = agent_launch.worker_hooks(object())
    assert list(inspect.signature(create).parameters) == ["plan", "session_id", "label", "working_dir"]
    assert list(inspect.signature(stop).parameters) == ["session_id", "session_uuid"]


@pytest.mark.real_tmux
def test_big_agents_value_through_tmux_is_byte_exact(tmux_test_socket, tmp_path):
    definition = json.dumps({"description": "d", "prompt": "it's " * 800})
    spec = _spec(agent_type="big", definition_json=definition)
    plan = _plan(spec)
    record, folder = tmp_path / "rec.json", tmp_path / "slot"
    folder.mkdir()
    write_task_file_slot = folder
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    write_task_file(write_task_file_slot, spec)
    cmd = " ".join(shlex.quote(a) for a in [sys.executable, str(FAKE), str(record), *plan.extra_args, plan.opening_prompt])
    name = f"carnivore_jobtest{os.getpid()}"
    subprocess.run(["tmux", "-L", tmux_test_socket, "new-session", "-d", "-s", name, "-c", str(folder), cmd], check=True, timeout=20)
    try:
        for _ in range(100):
            if record.exists() and record.read_text():
                break
            time.sleep(0.1)
        got = json.loads(record.read_text())
        assert got["argv"] == [*plan.extra_args, plan.opening_prompt]
        assert got["task_read"] == SECRET_TASK and got["task_mode"] == "0o600" and SECRET_TASK not in json.dumps(got["argv"])
    finally:
        subprocess.run(["tmux", "-L", tmux_test_socket, "kill-session", "-t", f"={name}"], check=False, timeout=10)
