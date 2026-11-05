
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_gr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_gr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import session_groups_routes
from src.api.auth import require_auth
from src.api.session_group_rule_routes import router as rule_router
from src.api.session_groups_routes import router as groups_router
from src.core.db_migration import ensure_db_migrated


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    monkeypatch.setattr(session_groups_routes.session_change_notice, "publish", lambda state, notice: None)
    assert ensure_db_migrated(tmp_path).status == "ok"
    app = FastAPI()
    app.include_router(groups_router, prefix="/api/v1")
    app.include_router(rule_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as c:
        yield c


def _group(c, uuid):
    return next(g for g in c.get("/api/v1/session-groups").json()["groups"] if g["group_uuid"] == uuid)


def test_the_rule_round_trips_and_clears(client):
    made = client.post("/api/v1/session-groups", json={"name": "api"}).json()["groups"][0]["group_uuid"]
    assert _group(client, made)["rule"] is None
    r = client.put(f"/api/v1/session-groups/{made}/rule", json={"flags": ["coffee", "running", "running"], "prefix": " api ", "suffix": None})
    assert r.status_code == 200
    assert _group(client, made)["rule"] == {"flags": ["running", "coffee"], "prefix": "api", "suffix": ""}
    client.put(f"/api/v1/session-groups/{made}/rule", json={"flags": [], "prefix": "", "suffix": ""})
    assert _group(client, made)["rule"] is None


def test_an_unknown_flag_is_a_400_and_a_missing_group_a_404(client):
    made = client.post("/api/v1/session-groups", json={"name": "api"}).json()["groups"][0]["group_uuid"]
    assert client.put(f"/api/v1/session-groups/{made}/rule", json={"flags": ["bogus"]}).status_code == 400
    assert client.put("/api/v1/session-groups/nope/rule", json={"flags": ["running"]}).status_code == 404
