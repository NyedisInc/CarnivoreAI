
from __future__ import annotations

from contextlib import closing

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import projects_routes
from src.api.auth import require_auth
from src.core.db import connect
from tests.python.launch_profiles.test_launch_profiles_routes import env  # noqa: F401


def _client(env_) -> TestClient:  # noqa: ANN001
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: True
    app.include_router(projects_routes.router, prefix="/api/v1")
    return TestClient(app)


def _stored(env_) -> object:  # noqa: ANN001
    with closing(connect(env_.db, create=False)) as conn:
        return conn.execute("SELECT default_agent_type FROM projects WHERE display_name = 'p'").fetchone()[0]


def test_default_launch_profile_roundtrip_and_refusals(env, monkeypatch):  # noqa: F811
    with closing(connect(env.db, create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, created_at, updated_at) "
                     "VALUES ('/p', '/p', 'p', 'test', 't', 't')")
        conn.commit()
    from src.config import settings
    from src.core.launch_profiles.store import LaunchProfileStore

    store = LaunchProfileStore(env.config)
    monkeypatch.setattr(type(settings), "get_launch_profiles", lambda self: store.read().profiles, raising=False)
    c = _client(env)
    ok = c.patch("/api/v1/projects/p", json={"default_launch_profile": "claude-spare"})
    assert ok.status_code == 200 and ok.json()["default_launch_profile"] == "claude-spare"
    assert _stored(env) == "claude-spare"
    for bad in ("no-such-profile", "claude"):
        refused = c.patch("/api/v1/projects/p", json={"default_launch_profile": bad})
        assert refused.status_code == 400 and refused.json()["detail"]["code"] == "launch_profile_needed"
    assert _stored(env) == "claude-spare"
    listed = {p["name"]: p for p in c.get("/api/v1/projects").json()}
    assert listed["p"]["default_launch_profile"] == "claude-spare"
    cleared = c.patch("/api/v1/projects/p", json={"default_launch_profile": ""})
    assert cleared.status_code == 200 and cleared.json()["default_launch_profile"] is None
    assert _stored(env) is None
