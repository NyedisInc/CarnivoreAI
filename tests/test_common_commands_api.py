from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.auth_routes import router as auth_router
from src.config import settings
from src.core import slash_command_labels, slash_favorites

DEFAULTS = slash_command_labels.DEFAULT_COMMON_COMMANDS
FAVORITE_URL = "/api/v1/config/common-commands/favorite"
LIST_URL = "/api/v1/config/common-commands"


@pytest.fixture()
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"projects": [], "agents": {}}, indent=2))
    monkeypatch.setattr(settings, "auth_config_file", str(path))
    settings._auth_config_cache = None
    yield path
    settings._auth_config_cache = None


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def _stored(path: Path):
    return json.loads(path.read_text()).get(slash_favorites.FAVORITES_KEY)



def test_get_shape_is_unchanged_for_an_old_client(client, config_path):
    data = client.get(LIST_URL).json()
    assert isinstance(data["commands"], list)
    assert all(isinstance(c, str) for c in data["commands"])
    assert [d["command"] for d in data["command_details"]] == data["commands"]
    assert all("description" in d for d in data["command_details"])


def test_get_on_a_config_with_no_key_reports_defaults_AS_defaults(client, config_path):
    data = client.get(LIST_URL).json()
    assert data["commands"] == DEFAULTS
    assert data["defaulted"] is True


def test_get_on_an_explicitly_empty_list_stays_empty(client, config_path):
    stored = json.loads(config_path.read_text())
    stored[slash_favorites.FAVORITES_KEY] = []
    config_path.write_text(json.dumps(stored))
    data = client.get(LIST_URL).json()
    assert data["commands"] == []
    assert data["defaulted"] is False



def test_starring_persists_and_returns_the_new_row(client, config_path):
    resp = client.post(FAVORITE_URL, json={"command": "/diff", "favorite": True})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "/diff" in data["commands"]
    assert data["defaulted"] is False
    assert "/diff" in _stored(config_path)


def test_unstarring_a_default_survives_a_reread(client, config_path):
    assert client.post(
        FAVORITE_URL, json={"command": "/clear", "favorite": False}
    ).status_code == 200
    again = client.get(LIST_URL).json()
    assert "/clear" not in again["commands"]
    assert again["defaulted"] is False


def test_unstarring_everything_leaves_an_empty_row_not_the_defaults(client, config_path):
    for command in list(DEFAULTS):
        client.post(FAVORITE_URL, json={"command": command, "favorite": False})
    data = client.get(LIST_URL).json()
    assert data["commands"] == []
    assert data["defaulted"] is False


def test_the_response_and_a_fresh_get_agree(client, config_path):
    posted = client.post(
        FAVORITE_URL, json={"command": "/review", "favorite": True}
    ).json()
    assert client.get(LIST_URL).json() == posted


def test_a_hand_authored_object_entry_survives_a_later_star(client, config_path):
    stored = json.loads(config_path.read_text())
    stored[slash_favorites.FAVORITES_KEY] = [
        {"command": "/deploy", "description": "ship it"}
    ]
    config_path.write_text(json.dumps(stored))
    client.post(FAVORITE_URL, json={"command": "/diff", "favorite": True})
    on_disk = _stored(config_path)
    assert on_disk[0] == {"command": "/deploy", "description": "ship it"}
    assert on_disk[1] == "/diff"
    details = client.get(LIST_URL).json()["command_details"]
    assert details[0] == {"command": "/deploy", "description": "ship it", "color": None}


def test_starring_twice_is_idempotent(client, config_path):
    first = client.post(FAVORITE_URL, json={"command": "/diff", "favorite": True}).json()
    second = client.post(FAVORITE_URL, json={"command": "/diff", "favorite": True}).json()
    assert first == second
    assert _stored(config_path).count("/diff") == 1


def test_a_blank_command_is_a_400_with_a_reason(client, config_path):
    resp = client.post(FAVORITE_URL, json={"command": "  ", "favorite": True})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_request"
    assert _stored(config_path) is None, "a refused toggle must not write"


def test_past_the_cap_is_a_400_and_writes_nothing(client, config_path):
    stored = json.loads(config_path.read_text())
    stored[slash_favorites.FAVORITES_KEY] = [
        f"/c{i}" for i in range(slash_favorites.MAX_FAVORITES)
    ]
    config_path.write_text(json.dumps(stored))
    resp = client.post(FAVORITE_URL, json={"command": "/one-more", "favorite": True})
    assert resp.status_code == 400
    assert "/one-more" not in _stored(config_path)


def test_an_unknown_field_is_refused_rather_than_ignored(client, config_path):
    resp = client.post(
        FAVORITE_URL, json={"command": "/diff", "favorite": True, "pinned": True}
    )
    assert resp.status_code == 422


def test_a_missing_favorite_field_is_refused(client, config_path):
    assert client.post(FAVORITE_URL, json={"command": "/diff"}).status_code == 422


def test_the_write_leaves_a_backup_and_no_stray_tmp(client, config_path):
    client.post(FAVORITE_URL, json={"command": "/diff", "favorite": True})
    assert config_path.with_suffix(".json.bak").exists()
    assert not config_path.with_suffix(".json.tmp").exists()
