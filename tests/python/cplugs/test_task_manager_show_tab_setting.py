
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import routes as host_routes, runtime


def make_app(state_dir: Path) -> FastAPI:
    app = FastAPI()
    host = runtime.install(app, state_dir)
    host.published = []
    host.publish = host.published.append
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.test_host = host
    return app


def test_show_tab_defaults_on_persists_and_rejects_a_non_boolean(tmp_path: Path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        row = client.get("/api/v1/cplugs/huddle").json()
        assert row["settings"].get("showTab", True) is True
        bad = client.put("/api/v1/cplugs/huddle", json={"revision": row["revision"], "settings": {"showTab": "no"}})
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "settings_invalid"
        done = client.put("/api/v1/cplugs/huddle", json={"revision": row["revision"], "settings": {"showTab": False}})
        assert done.status_code == 200 and done.json()["settings"]["showTab"] is False
        assert "cplugs" in app.state.test_host.published
    with TestClient(make_app(tmp_path)) as client:
        assert client.get("/api/v1/cplugs/huddle").json()["settings"]["showTab"] is False
