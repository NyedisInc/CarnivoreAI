
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import imported_restart_routes as routes
from src.api.auth import require_auth
from src.core.account_switch import session_pin
from src.core.pack.move import account
from src.core.pack.relay import target_side
from src.core.session_imported_restart import DIRECTORY_MEASURED, ResumeDirectory
from tests.test_session_imported_restart import ROW_UUID, _insert
from src.core.db_migration import ensure_db_migrated

ACCOUNT = "claude-code-larkspur"


@pytest.fixture()
def machine(tmp_path, monkeypatch):
    from src.config import settings

    home, state = tmp_path / "home", tmp_path / "state"
    home.mkdir()
    state.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({}))
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    assert ensure_db_migrated(state).status == "ok"
    created = []

    class Manager:
        async def create_session(self, **kw):
            created.append(kw)
            return SimpleNamespace(id="ses_new")

    monkeypatch.setattr(routes, "resume_directory", lambda *a, **k: ResumeDirectory(outcome=DIRECTORY_MEASURED, working_dir="/Users/x/proj"))
    monkeypatch.setattr(routes, "validate_agent_choice", lambda *a, **k: SimpleNamespace(verdict="accepted", command="claude --resume x", detail=""))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = Manager()
    _insert(state)
    with TestClient(app) as client:
        yield client, home, config, created


def _restart(client):
    return client.post("/api/v1/sessions/imported/restart", json={"session_uuid": ROW_UUID, "agent_type": "claude"})


def test_a_relay_backed_session_launches_on_the_relay_profile_and_an_unrunnable_one_creates_no_pane(machine) -> None:
    client, home, config, created = machine
    assert _restart(client).json()["status"] == "started" and created[-1]["extra_env"] is None and created[-1]["claude_account"] is None

    assert session_pin.carry(config, ROW_UUID, ACCOUNT)
    created.clear()
    refused = _restart(client).json()
    assert refused["status"] == "refused" and refused["code"] == account.NOT_USABLE_CODE and created == []

    profile = Path(target_side.relay_profile_dir(ACCOUNT, "iid-mac", home))
    profile.mkdir(parents=True)
    started = _restart(client).json()
    assert started["status"] == "started"
    assert created[-1]["extra_env"] == {"CLAUDE_CONFIG_DIR": str(profile)}


def test_a_carried_pin_never_overrides_the_owners_own_pin_and_a_bad_key_is_ignored(machine) -> None:
    _client, _home, config, _created = machine
    assert session_pin.carry(config, "u1", "work") and not session_pin.carry(config, "u1", "other")
    assert session_pin.pin_for(config, "u1") == "work" and not session_pin.carry(config, "u2", "Not A Slug")
