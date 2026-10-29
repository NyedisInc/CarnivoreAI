
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.config  # noqa: F401
from src.api import automation_command_routes
from src.api.auth import require_auth
from src.core.automations import command_allowlist, targets
from src.core.automations import models as m
from src.core.automations.store import AutomationStore
from src.core.automations.store_schema import storage_for
from src.core.automations.targets import command
from src.core.resource_push import topics


@pytest.fixture
def world(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"keep_me": 1}))
    monkeypatch.setattr(command_allowlist, "config_path", lambda: path)
    announced = []
    monkeypatch.setattr(command_allowlist.resource_push, "notify", announced.append)
    monkeypatch.setitem(targets.VALIDATORS, "command", command.validate_target)
    monkeypatch.setitem(targets.RUNNERS, "command", command.run)
    store = AutomationStore(storage_for(tmp_path), notify=lambda _t: None)
    return SimpleNamespace(path=path, store=store, announced=announced)


def _save(world, name, text):
    return world.store.create(name=name, cron="0 7 * * 1", target={"kind": "command", "command": text})


def test_a_command_target_is_refused_unless_it_matches_an_entry_exactly(world):
    with pytest.raises(m.AutomationInvalid) as exc:
        _save(world, "empty", "/bin/echo hi")
    assert "command_not_allowed" in str(exc.value)
    command_allowlist.save(["/bin/echo hi"])
    saved = _save(world, "ok", "/bin/echo hi")
    for near in ("/bin/echo  hi", "/bin/echo hi ", "/bin/echo hello", "echo hi", "/bin/echo"):
        with pytest.raises(m.AutomationInvalid):
            _save(world, f"near{len(near)}", near)
    command_allowlist.save([])
    run = world.store.insert_run(saved["automation_id"], "boot")
    ctx = SimpleNamespace(app_state=SimpleNamespace(), store=world.store, boot_id="boot")
    outcome = asyncio.run(command.run(ctx, saved, run))
    assert outcome.status == m.FAILED and outcome.reason == "command_not_allowed"


def test_entries_are_checked_and_stored_beside_the_other_config_keys(world):
    for bad in ("", "   ", "git pull", "/usr/bin/git 'unclosed", "/bin/echo a\nb", "x" * 600):
        with pytest.raises(command_allowlist.CommandListInvalid):
            command_allowlist.clean_entry(bad)
    assert command_allowlist.save(["  /bin/echo a ", "/bin/echo a", "/bin/true"]) == ["/bin/echo a", "/bin/true"]
    stored = json.loads(world.path.read_text())
    assert stored["keep_me"] == 1 and stored[command_allowlist.CONFIG_KEY] == ["/bin/echo a", "/bin/true"]
    assert world.announced == [topics.AUTOMATION_COMMANDS]
    command_allowlist.save(["/bin/echo a", "/bin/true"])
    assert world.announced == [topics.AUTOMATION_COMMANDS]


def test_the_routes_read_and_replace_the_list(world):
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(automation_command_routes.router)
    client = TestClient(app)
    assert client.get("/automation-commands").json()["commands"] == []
    put = client.put("/automation-commands", json={"commands": ["/bin/true"]})
    assert put.status_code == 200 and client.get("/automation-commands").json()["commands"] == ["/bin/true"]
    bad = client.put("/automation-commands", json={"commands": ["rm -rf /"]})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "command_invalid"
