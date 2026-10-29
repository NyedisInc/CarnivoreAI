
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import recreate_routes, session_records_routes, session_rename_routes, session_sleep_routes
from src.api.auth import require_auth
from tests.test_session_sleep import NAME, ROW_UUID, _insert, _row, state_dir  # noqa: F401


def test_an_asleep_session_renames_without_tmux_and_wakes_under_the_new_name(state_dir, monkeypatch):
    _insert(state_dir, lifecycle="stopped", source="slept_by_user")
    tmux_calls = []
    for attr in ("_measure_presence",):
        monkeypatch.setattr(recreate_routes, attr, lambda *a, **k: tmux_calls.append(a), raising=True)

    woken = []

    async def _recreate(session_uuid, agent_type, *, get_manager, row_overrides=None):
        woken.append(_row(state_dir, session_uuid)["title"])
        return recreate_routes.RecreateResponse(
            status="started", session_uuid=session_uuid, session_name=NAME,
            presence="gone", conversation="resumed", detail="resumed")

    monkeypatch.setattr("src.api.recreate_action.recreate_by_uuid", _recreate)
    monkeypatch.setattr("src.core.session_agent_choice.configured_wrapper_ids", lambda s: None)

    app = FastAPI()
    for router in (session_rename_routes.router, session_sleep_routes.router, session_records_routes.router):
        app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = SimpleNamespace(set_session_label=lambda sid, label: False)
    app.state.local_servers = SimpleNamespace()
    with TestClient(app) as c:
        r = c.patch(f"/api/v1/sessions/{ROW_UUID}/name", json={"new_name": "my renamed bot"})
        assert r.status_code == 200, r.text
        assert r.json()["label"] == "my renamed bot"
        row = _row(state_dir)
        assert row["title"] == "my renamed bot"
        assert (row["tmux_name"], row["lifecycle"]) == (NAME, "stopped"), "identity and asleep marker untouched"
        assert tmux_calls == [], "an asleep rename makes no tmux call"
        listed = {x["session_uuid"]: x for x in c.get("/api/v1/sessions/records").json()}
        assert listed[ROW_UUID]["title"] == "my renamed bot"
        assert c.post(f"/api/v1/sessions/{ROW_UUID}/wake").json()["status"] == "started"
    assert woken == ["my renamed bot"]


def test_an_unknown_target_is_still_a_404(state_dir):
    app = FastAPI()
    app.include_router(session_rename_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.session_manager = SimpleNamespace(set_session_label=lambda sid, label: False)
    with TestClient(app) as c:
        assert c.patch("/api/v1/sessions/nope/name", json={"new_name": "x"}).status_code == 404
