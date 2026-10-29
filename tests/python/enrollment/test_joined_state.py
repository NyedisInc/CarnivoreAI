
import json
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_joined_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_joined_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

import src.api.auth as auth_mod  # noqa: E402
import src.api.enrollment_routes as enrollment_routes  # noqa: E402
from src.api.joined_lockdown import JoinedLockdownMiddleware  # noqa: E402
from src.config import settings  # noqa: E402
from src.core import setup_state  # noqa: E402
from src.core.computers import invites, membership, store  # noqa: E402
from src.core.computers.store import LinkRow  # noqa: E402

PORT = settings.port


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"agents": {}}))
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    monkeypatch.setattr(settings, "totp_secret", "JBSWY3DPEHPK3PXP")
    monkeypatch.setattr(settings, "jwt_secret", "test-jwt-secret-not-a-real-one-32b")
    settings.drop_auth_config_cache()
    monkeypatch.setattr(membership, "_join_running", False)
    store.CACHE.replace([])
    monkeypatch.setattr(enrollment_routes, "env_file_path", lambda: tmp_path / "absent.env")
    auth_mod.limiter.reset()

    inner = FastAPI()
    inner.state.limiter = auth_mod.limiter
    inner.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    inner.include_router(enrollment_routes.router, prefix="/api/v1")

    @inner.get("/probe")
    async def probe():
        return {"ok": True}

    ticks = iter(range(0, 10**9, 10))
    inner.add_middleware(JoinedLockdownMiddleware, clock=lambda: float(next(ticks)))

    class Tag:
        def __init__(self, app, updates):
            self.app, self.updates = app, updates

        async def __call__(self, scope, receive, send):
            await self.app(dict(scope, **self.updates) if scope["type"] in ("http", "websocket") else scope, receive, send)

    class Env:
        marker = tmp_path / ".pack_joined"
        sentinel = tmp_path / ".totp_paired"
        config = cfg

        @staticmethod
        def client(client=("127.0.0.1", 50000), updates=None):
            return TestClient(Tag(inner, updates or {}), base_url=f"http://127.0.0.1:{PORT}", client=client)

    yield Env()
    settings.drop_auth_config_cache()
    store.CACHE.replace([])
    auth_mod.limiter.reset()


def test_state_walk(env):
    assert membership.first_run_state() == "unpaired"
    env.sentinel.touch()
    assert membership.first_run_state() == "paired"
    env.sentinel.unlink()
    membership.set_join_running(True)
    assert membership.first_run_state() == "join_pending"
    membership.set_join_running(False)
    store.CACHE.replace([LinkRow("main-iid", "main", "tls", "2026-10-10T00:00:00Z", joined_at="2026-10-10T00:00:00Z")])
    assert membership.first_run_state() == "join_pending"
    store.CACHE.replace([LinkRow("main-iid", "main", "tls", "x", joined_at="y", first_link_at="z")])
    assert membership.first_run_state() == "unpaired"
    env.sentinel.touch()
    env.marker.touch()
    membership.set_join_running(True)
    assert membership.first_run_state() == "joined" and membership.is_member()
    membership.set_join_running(False)


def test_marker_stands_in_for_the_sentinel(env):
    state = setup_state.current_setup_state()
    assert state.joined is False and not state.is_complete
    env.marker.touch()
    state = setup_state.current_setup_state()
    assert state.joined is True and state.is_complete
    exposure = setup_state.resolve_exposure("0.0.0.0", state)
    assert exposure.bind_host == "127.0.0.1" and exposure.wizard_requires_auth and exposure.locked_down
    assert "joined a pack" in exposure.reason
    assert not setup_state.resolve_exposure("127.0.0.1", state).locked_down


def test_undetermined_when_the_marker_cannot_be_read(env, monkeypatch):
    real = setup_state._exists
    monkeypatch.setattr(setup_state, "_exists", lambda p: None if p.name == ".pack_joined" else real(p))
    assert membership.first_run_state() == "undetermined"


def test_health_fields(env):
    from src import main  # noqa: PLC0415

    body = TestClient(main.app).get("/health").json()
    assert body["joined"] is False and body["rebind_requested"] is False
    assert "door_file" in body
    env.marker.touch()
    membership.request_rebind()
    try:
        body = TestClient(main.app).get("/health").json()
        assert body["joined"] is True and body["rebind_requested"] is True
    finally:
        membership._rebind_requested = False


def test_enrollment_status_and_409(env):
    c = env.client()
    first = c.get("/api/v1/auth/enrollment/status")
    assert first.json()["joined"] is False
    membership.set_join_running(True)
    assert c.get("/api/v1/auth/enrollment/status").json()["join_pending"] is True
    membership.set_join_running(False)
    env.marker.touch()
    status = c.get("/api/v1/auth/enrollment/status").json()
    assert status["joined"] is True and status["join_pending"] is False
    resp = c.get("/api/v1/auth/enrollment")
    assert resp.status_code == 409 and resp.json()["detail"] == {"reason": "joined"}
    assert "JBSWY3DPEHPK3PXP" not in resp.text


def test_lockdown_only_while_joined(env):
    lan = env.client(client=("198.51.100.18", 50000))
    assert lan.get("/probe").status_code == 200
    env.marker.touch()
    env2 = env.client(client=("198.51.100.18", 50000))
    resp = env2.get("/probe")
    assert resp.status_code == 403 and resp.json() == {"detail": {"reason": "joined_local_only"}}


@pytest.mark.parametrize("client,updates,status", [
    (("127.0.0.1", 1), {}, 200),
    (("::1", 1), {}, 200),
    (("198.51.100.18", 1), {}, 403),
    (("198.51.100.18", 1), {"via_peer_link": True}, 200),
    (("127.0.0.1", 1), {"via_link": True}, 403),
    (("127.0.0.1", 1), {"via_link": True, "via_peer_link": True}, 403),
    (None, {}, 403),
])
def test_lockdown_matrix(env, client, updates, status):
    env.marker.touch()
    c = env.client(client=client or ("127.0.0.1", 1), updates=updates)
    if client is None:
        c = env.client(updates={"client": None})
    assert c.get("/probe").status_code == status


def test_lockdown_websocket_closed(env):
    from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

    env.marker.touch()
    with pytest.raises(WebSocketDisconnect):
        with env.client(client=("198.51.100.18", 1)).websocket_connect("/ws"):
            pass


def test_stat_cache_two_seconds(tmp_path):
    marker = tmp_path / ".pack_joined"
    now = [100.0]
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    mw = JoinedLockdownMiddleware(app, marker=lambda: marker, clock=lambda: now[0])
    assert mw._is_joined() is False
    marker.touch()
    now[0] += 1.0
    assert mw._is_joined() is False
    now[0] += 1.5
    assert mw._is_joined() is True


def test_member_mints_no_invites():
    inv = invites.Invites(is_member=lambda: True)
    with pytest.raises(invites.MemberRefused):
        inv.mint()
    assert invites.Invites().mint().kind == "code"
