
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import mods_routes
from src.core.mods import registry
from tests.python.route_tests.harness import client_for


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    mod = home / ".claude" / "mods" / "alpha"
    (mod / "hooks").mkdir(parents=True)
    (mod / "hooks" / "hooks.json").write_text('{"modules": ["./register.js"]}')
    settings_file = home / ".claude" / "settings.json"
    settings_file.write_text(json.dumps({"theme": "dark"}))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(mods_routes, "account_settings_files", lambda: ([], mods_routes.ACCOUNTS_OK))
    monkeypatch.setattr(mods_routes, "_ledger_rows", lambda request: [])
    monkeypatch.setattr(mods_routes, "detect_claude_version", lambda: None)
    client = client_for(mods_routes.router, prefix="/api/v1")
    mod_id = client.get("/api/v1/mods").json()["mods"][0]["mod_id"]
    return client, mod_id, settings_file, mod


def _registered(settings_file: Path) -> str:
    return json.loads(settings_file.read_text()).get("env", {}).get(registry.ENV_KEY, "")


def test_turning_a_mod_on_then_off_registers_and_unregisters_it(world) -> None:
    client, mod_id, settings_file, mod = world
    on = client.put(f"/api/v1/mods/{mod_id}/enabled", json={"enabled": True})
    assert on.status_code == 200, on.text
    assert on.json()["mod"]["state"] == "on" and str(mod) in _registered(settings_file)
    assert json.loads(settings_file.read_text())["theme"] == "dark", "other settings are untouched"
    off = client.put(f"/api/v1/mods/{mod_id}/enabled", json={"enabled": False})
    assert off.json()["mod"]["state"] == "off" and str(mod) not in _registered(settings_file)
    assert mod.is_dir(), "switching off never deletes the folder"


@pytest.mark.parametrize("mod_id", ["0123456789abcdef", "../../etc", "NOTHEX"])
def test_an_unknown_or_malformed_id_is_a_404_and_changes_nothing(world, mod_id: str) -> None:
    client, _, settings_file, _ = world
    before = settings_file.read_text()
    assert client.put(f"/api/v1/mods/{mod_id}/enabled", json={"enabled": True}).status_code in (404, 405)
    assert settings_file.read_text() == before


def test_turning_on_a_folder_that_is_gone_is_a_409_folder_missing(world) -> None:
    client, mod_id, settings_file, mod = world
    client.put(f"/api/v1/mods/{mod_id}/enabled", json={"enabled": True})
    mod.rename(mod.parent / "alpha-moved")
    before = settings_file.read_text()
    resp = client.put(f"/api/v1/mods/{mod_id}/enabled", json={"enabled": True})
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "folder_missing"
    assert settings_file.read_text() == before


def test_an_unreadable_account_list_refuses_the_write(world, monkeypatch: pytest.MonkeyPatch) -> None:
    client, mod_id, settings_file, _ = world
    monkeypatch.setattr(mods_routes, "account_settings_files", lambda: ([], mods_routes.ACCOUNTS_UNREADABLE))
    before = settings_file.read_text()
    resp = client.put(f"/api/v1/mods/{mod_id}/enabled", json={"enabled": True})
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "accounts_unreadable"
    assert settings_file.read_text() == before


def test_a_body_without_the_flag_is_a_422(world) -> None:
    client, mod_id, _, _ = world
    assert client.put(f"/api/v1/mods/{mod_id}/enabled", json={}).status_code == 422
    assert client.put(f"/api/v1/mods/{mod_id}/enabled", json={"enabled": True, "x": 1}).status_code == 422


def test_the_route_needs_auth() -> None:
    client = client_for(mods_routes.router, signed_in=False, prefix="/api/v1")
    assert client.put("/api/v1/mods/0123456789abcdef/enabled", json={"enabled": True}).status_code in (401, 403)
