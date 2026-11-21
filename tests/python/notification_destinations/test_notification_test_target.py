
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import notification_test_routes as test_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.notifications import engine as eng, routing_view, test_toast  # noqa: E402
from src.core.notifications.engine import SendTestOutcome  # noqa: E402
from src.core.sessions.toast_inbox import ToastInbox  # noqa: E402
from tests.python.notifications.engine_fakes import FakeView, dest  # noqa: E402

URL = "/api/v1/notifications/test"
TYPE = "session.finished"


class FakeEngine:

    def __init__(self):
        self.sent = []

    async def send_test(self, dest_id, type_id=None):
        self.sent.append((dest_id, type_id))
        return SendTestOutcome(found=True, result=SimpleNamespace(ok=True, failure=None, status_code=200))


@pytest.fixture(autouse=True)
def _clean():
    test_routes._last.clear()
    routing_view.uninstall_routing()
    eng.install_engine(None)
    yield
    routing_view.uninstall_routing()
    eng.install_engine(None)


@pytest.fixture
def rig(monkeypatch):
    fake = FakeEngine()
    eng.install_engine(fake)
    routing_view.install_routing(lambda: FakeView([dest(1, kind="apns"), dest(2, kind="webpush"), dest(3)]), SimpleNamespace())
    manager = SimpleNamespace(_toast_inbox=ToastInbox(), _registry=SimpleNamespace(sessions={"ses_1": SimpleNamespace(tmux_session="carnivore_x")}))
    sent = []

    async def broadcast(toast, app_state):
        sent.append(toast)

    monkeypatch.setattr(test_toast, "broadcast", broadcast)
    app = FastAPI()
    app.include_router(test_routes.router, prefix="/api/v1")
    app.state.session_manager = manager
    app.dependency_overrides[require_auth] = lambda: None
    return SimpleNamespace(client=TestClient(app), engine=fake, sent=sent, manager=manager, app=app)


def test_refuses_unauthenticated():
    app = FastAPI()
    app.include_router(test_routes.router, prefix="/api/v1")
    assert TestClient(app).post(URL, json={"type_id": TYPE, "target": "app"}).status_code in (401, 403)


def test_phone_sends_to_every_push_destination_and_ignores_other_kinds(rig):
    eng_fake = rig.engine
    r = rig.client.post(URL, json={"type_id": TYPE, "target": "phone"})
    assert r.status_code == 200 and r.json() == {"ok": True, "failure": None, "status_code": None, "target": "phone", "delivered": 2}
    assert sorted(eng_fake.sent) == [("d_000000000001", TYPE), ("d_000000000002", TYPE)]
    assert rig.client.post(URL, json={"type_id": TYPE, "target": "phone"}).status_code == 429


def test_phone_without_a_push_destination_is_404_no_phone(rig):
    routing_view.install_routing(lambda: FakeView([dest(3)]), SimpleNamespace())
    r = rig.client.post(URL, json={"type_id": TYPE, "target": "phone"})
    assert r.status_code == 404 and r.json() == {"detail": {"error": "no_phone"}}


@pytest.mark.parametrize("target", ["app", "desktop"])
def test_app_and_desktop_raise_a_marked_toast_that_is_never_emitted(rig, target):
    r = rig.client.post(URL, json={"type_id": TYPE, "target": target})
    assert r.status_code == 200 and r.json()["target"] == target and r.json()["delivered"] == 1
    (toast,) = rig.sent
    assert toast.test_target == target and toast.notify_type == TYPE and toast.session_id == "ses_1"
    assert rig.engine.sent == []
    assert rig.client.post(URL, json={"type_id": TYPE, "target": target}).status_code == 429
    from src.core.notifications.sources import toast as toast_source
    assert toast_source.test_target_for_toast_id(rig.manager, toast.id) == target


def test_bad_bodies_and_a_stopped_engine(rig):
    assert rig.client.post(URL, json={"type_id": "no.such", "target": "app"}).status_code == 422
    assert rig.client.post(URL, json={"type_id": TYPE, "target": "fax"}).status_code == 422
    assert rig.client.post(URL, json={"type_id": TYPE, "target": "app", "x": 1}).status_code == 422
    eng.install_engine(None)
    assert rig.client.post(URL, json={"type_id": TYPE, "target": "app"}).status_code == 503


def test_no_live_session_is_409_and_does_not_start_the_window(rig):
    rig.manager._registry.sessions.clear()
    assert rig.client.post(URL, json={"type_id": TYPE, "target": "app"}).status_code == 409
    rig.manager._registry.sessions["ses_1"] = SimpleNamespace(tmux_session="x")
    assert rig.client.post(URL, json={"type_id": TYPE, "target": "app"}).status_code == 200
