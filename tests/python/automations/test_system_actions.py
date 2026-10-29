
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

import src.config  # noqa: F401
from src.core.automations import command_allowlist, gates, system_actions, targets
from src.core.automations import models as m
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.automations.targets import command, recipe
from src.core.session_delivery import bring_up


@pytest.fixture
def config_json(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{}")
    monkeypatch.setattr(command_allowlist, "config_path", lambda: path)
    return path


@pytest.fixture
def store(tmp_path, monkeypatch, config_json):
    monkeypatch.setitem(targets.RUNNERS, "recipe", recipe.run)
    monkeypatch.setitem(targets.RUNNERS, "command", command.run)
    monkeypatch.setitem(targets.VALIDATORS, "command", command.validate_target)
    monkeypatch.setattr(recipe.notify_policy, "tell", lambda *a, **k: None)
    return AutomationStore(storage_for(tmp_path), notify=lambda _t: None)


def _ctx(store, **state):
    return SimpleNamespace(app_state=SimpleNamespace(**state), store=store, boot_id="boot")


def _go(store, target, ctx=None, name="a"):
    automation = store.create(name=name, cron="0 7 * * 1", target=target)
    run = store.insert_run(automation["automation_id"], "boot")
    runner = targets.RUNNERS[target["kind"]]
    return asyncio.run(runner(ctx or _ctx(store), automation, run))


def test_registry_lists_exactly_the_named_actions_and_none_spends():
    assert tuple(system_actions.REGISTRY) == m.SYSTEM_ACTIONS
    for name in m.SYSTEM_ACTIONS:
        assert gates.spends({"kind": "recipe", "recipe": name}) is False
    assert gates.spends({"kind": "recipe", "recipe": "scrooge"}) is True
    assert gates.spends({"kind": "command", "command": "/bin/x"}) is False


def test_save_checks_action_params(store):
    store.create(name="ok", cron="0 7 * * 1", target={"kind": "recipe", "recipe": "sleep_idle_sessions"})
    with pytest.raises(m.AutomationInvalid) as exc:
        store.create(name="bad", cron="0 7 * * 1", target={"kind": "recipe", "recipe": "restart_session"})
    assert exc.value.code == "target_invalid"
    with pytest.raises(m.AutomationInvalid):
        store.create(name="long", cron="0 7 * * 1",
                     target={"kind": "recipe", "recipe": "send_notification", "params": {"text": "x" * 281}})


def test_the_command_allow_list_ships_empty_and_refuses_at_save(store):
    assert command_allowlist.read() == []
    with pytest.raises(m.AutomationInvalid) as exc:
        store.create(name="c", cron="0 7 * * 1", target={"kind": "command", "command": "/usr/bin/git fetch", "project_id": 1})
    assert exc.value.code == "target_invalid" and "command_not_allowed" in str(exc.value)
    with pytest.raises(m.AutomationInvalid):
        m.validate_target({"kind": "command", "command": "/bin/x", "argv": ["/bin/sh", "-c", "rm -rf /"]})


def test_command_runs_the_listed_text_with_a_built_env_and_redacted_tail(store, monkeypatch):
    command_allowlist.save(["/usr/bin/env"])
    monkeypatch.setenv("CARNIVORE_TEST_SECRET_VAR", "sk-ant-api03-" + "A" * 90)
    outcome = _go(store, {"kind": "command", "command": "/usr/bin/env"})
    assert outcome.status == m.SUCCEEDED and outcome.report["exit_code"] == 0
    assert "CARNIVORE_TEST_SECRET_VAR" not in outcome.report["stdout_tail"]
    assert "PATH=" in outcome.report["stdout_tail"]
    assert store.run(store.runs(outcome_automation_id(store))[0]["run_id"])["child"] is None


def outcome_automation_id(store):
    return store.list_all()[0]["automation_id"]


def test_command_nonzero_exit_fails_with_the_code_and_tail_is_redacted(store):
    key = "sk-ant-api03-" + "B" * 90
    command_allowlist.save([f"/bin/echo {key}", "/usr/bin/false"])
    leaked = _go(store, {"kind": "command", "command": f"/bin/echo {key}"}, name="l")
    assert key not in leaked.report["stdout_tail"]
    failed = _go(store, {"kind": "command", "command": "/usr/bin/false"}, name="n")
    assert failed.status == m.FAILED and failed.reason == "exit_1"


def test_sleep_idle_sessions_runs_one_pass(store):
    async def pass_once():
        return ["u1", "u2"]

    ctx = _ctx(store, auto_sleeper=SimpleNamespace(pass_once=pass_once))
    outcome = _go(store, {"kind": "recipe", "recipe": "sleep_idle_sessions"}, ctx)
    assert outcome.status == m.SUCCEEDED and outcome.report == {"action": "sleep_idle_sessions", "slept": 2}
    missing = _go(store, {"kind": "recipe", "recipe": "sleep_idle_sessions"}, name="b")
    assert missing.status == m.FAILED and missing.reason == "auto_sleep_unavailable"


def test_restart_session_never_touches_a_live_session(store, monkeypatch):
    uuid = "0f6c2d6e-1111-4c4c-9e9e-000000000002"
    monkeypatch.setattr(bring_up, "ops_for_app", lambda app_state: None)

    async def find_live(ops, session_uuid):
        return SimpleNamespace(activity_status="working")

    monkeypatch.setattr(bring_up, "find_live", find_live)
    outcome = _go(store, {"kind": "recipe", "recipe": "restart_session", "params": {"session_uuid": uuid}})
    assert outcome.status == m.SKIPPED and outcome.reason == "session_live"


def test_a_measured_session_login_decides_the_usage_gate(monkeypatch):
    from src.core.byoai.contracts import ByoaiError
    from src.core.byoai.native import cli_run
    from src.core.swarm.cards import capacity

    def profile_dir(provider, account_id):
        if account_id == "gone":
            raise ByoaiError("no such login")
        return f"/profiles/{account_id}"

    monkeypatch.setattr(cli_run, "profile_dir", profile_dir)
    monkeypatch.setattr(capacity, "account_for", lambda profile: "default")
    target = {"kind": "session_message", "session_uuid": "x" * 8, "text": "t"}
    assert gates.login_of(target, "work") == ("work", "/profiles/work")
    assert gates.login_of(target, None) == ("default", None)
    assert gates.login_of(target, "gone") == ("default", None)
    assert os.environ.get("CARNIVORE_TEST_SECRET_VAR") is None
