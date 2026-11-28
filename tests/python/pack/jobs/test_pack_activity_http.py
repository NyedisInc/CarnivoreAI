
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import pack_jobs_metrics_routes as owner_routes
from src.api.auth import require_auth


def _client() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(username="alice")
    app.include_router(owner_routes.router, prefix="/api/v1")
    return TestClient(app)


def test_the_pack_activity_route_passes_its_query_to_the_builder(monkeypatch, tmp_path) -> None:
    seen: Dict[str, Any] = {}

    async def build(store, state_dir, *, days, limit, include_peers):
        seen.update(days=days, limit=limit, include_peers=include_peers, state_dir=state_dir)
        return {"live": [], "history": []}

    monkeypatch.setattr(owner_routes.boot, "engine", lambda: SimpleNamespace(store=SimpleNamespace(state_dir=tmp_path)))
    monkeypatch.setattr(owner_routes.pack_activity, "build_activity", build)
    response = _client().get("/api/v1/pack/activity?days=3&limit=10&include_peers=false")
    assert response.status_code == 200 and response.json() == {"live": [], "history": []}
    assert seen == {"days": 3, "limit": 10, "include_peers": False, "state_dir": tmp_path}


def test_the_pack_activity_route_refuses_days_outside_the_window() -> None:
    assert _client().get("/api/v1/pack/activity?days=0").status_code == 422
