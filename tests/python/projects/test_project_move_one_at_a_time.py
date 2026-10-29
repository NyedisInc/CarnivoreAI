
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import project_move_routes
from src.api.auth import require_auth
from src.api.routes import router as api_router
from src.core.project_move.apply import one_move_at_a_time
from tests.python.projects.move_world import NO_PANES, snapshot


def test_an_apply_while_another_move_runs_is_refused_and_a_plan_is_not(world, monkeypatch):
    monkeypatch.setattr(project_move_routes, "read_live_panes", lambda: NO_PANES)
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    client = TestClient(app)
    url = "/api/v1/projects/alpha/move"
    plan = client.post(url, json={"new_root": str(world.new), "move_folder": True}).json()
    before = snapshot(world)
    with one_move_at_a_time():
        assert client.post(url, json={"new_root": str(world.new), "move_folder": True}).status_code == 200
        busy = client.post(url, json={"new_root": str(world.new), "move_folder": True, "apply": True,
                                      "plan_fingerprint": plan["fingerprint"]})
    assert busy.status_code == 409 and "another project move is running" in busy.json()["detail"]["message"]
    assert snapshot(world) == before
    done = client.post(url, json={"new_root": str(world.new), "move_folder": True, "apply": True,
                                  "plan_fingerprint": plan["fingerprint"]})
    assert done.status_code == 200, done.text
