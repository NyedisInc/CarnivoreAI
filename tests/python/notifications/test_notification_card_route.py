
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import notification_types_routes as routes
from src.api.auth import require_auth
from src.core.sessions.toast_inbox import ToastInbox


def test_card_route_serves_a_toast_from_the_inbox() -> None:
    inbox = ToastInbox()
    toast, _ = inbox.store("ses_a", kind="info", title="build done", body="all green", color=None,
                           session_label="proj", session_name="proj", notify_type="session.finished")
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    app.state.session_manager = SimpleNamespace(_toast_inbox=inbox, _registry=SimpleNamespace(sessions={}))
    client = TestClient(app)
    ok = client.get(f"/api/v1/notifications/cards/{toast.id}")
    assert ok.status_code == 200, ok.text
    assert ok.json()["type"] == "session.finished"
    assert client.get("/api/v1/notifications/cards/nope").status_code == 404
