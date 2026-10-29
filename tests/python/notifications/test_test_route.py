
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import notification_test_routes as routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.notifications import engine as eng, routing_view  # noqa: E402
from src.core.notifications.contracts import FailureClass as F  # noqa: E402
from tests.python.notifications.engine_fakes import Clock, FakeSender, FakeView, FakeWriter, Sleeper, dest, fail  # noqa: E402

URL = "/api/v1/notifications/destinations/{}/test"
DID = "d_000000000001"


def _client(authed: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    routing_view.uninstall_routing()
    eng.install_engine(None)
    yield
    routing_view.uninstall_routing()
    eng.install_engine(None)


def _install(sender: FakeSender) -> None:
    clock = Clock()

    async def secrets(_):
        return {"token": "SECRET-VALUE"}

    engine = eng.NotifyEngine(sender_lookup=lambda k: sender, is_muted=lambda s: False, secrets_lookup=secrets,
                              clock=clock, sleep=Sleeper(clock))
    routing_view.install_routing(lambda: FakeView([dest(config={"url": "https://hook.example/x"})]), FakeWriter())
    eng.install_engine(engine)


def test_unauthenticated_is_refused():
    assert _client(authed=False).post(URL.format(DID)).status_code in (401, 403)


def test_503_without_engine():
    assert _client().post(URL.format(DID)).status_code == 503


def test_404_unknown_destination():
    _install(FakeSender())
    assert _client().post(URL.format("d_ffffffffffff")).status_code == 404


def test_ok_then_429_within_window_and_no_secret_in_body():
    sender = FakeSender()
    _install(sender)
    c = _client()
    first = c.post(URL.format(DID))
    assert first.status_code == 200 and first.json() == {"ok": True, "failure": None, "status_code": None}
    assert c.post(URL.format(DID)).status_code == 429
    assert len(sender.calls) == 1


def test_failure_class_and_status_code_reported():
    _install(FakeSender(fail(F.AUTH, status_code=401, detail="https://hook.example/x SECRET-VALUE")))
    body = _client().post(URL.format(DID)).json()
    assert body == {"ok": False, "failure": "auth", "status_code": 401}
