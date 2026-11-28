
import hashlib
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import link_status_routes
from src.api.auth import require_auth
from src.core.catalog import hosted_api
from src.core.phone_link import link_status
from src.core.relay_identity import device_key as dk

KEY = dk.DeviceKey.from_seed(bytes(range(32)))


class FakeSession:

    def __init__(self, status=200):
        self.posts, self.status = [], status

    async def key(self):
        return KEY

    async def post_signed(self, path, body):
        self.posts.append((path, body))
        return hosted_api.HostedAnswer(self.status, {})


def _verify(message: bytes, sig: str) -> None:
    Ed25519PublicKey.from_public_bytes(KEY.raw_pub).verify(dk.unb64url(sig), message)


@pytest.mark.asyncio
async def test_a_report_is_signed_over_status_and_a_rising_sequence():
    session = FakeSession()
    assert await link_status.report(session, "signed_out") and await link_status.report(session, "up")
    (path, first), (_, second) = session.posts
    assert path == "/link-status" and second["seq"] > first["seq"]
    _verify(dk.link_status_message(KEY.device_id, first["ts"], first["seq"], "signed_out"), first["sig"])
    with pytest.raises(Exception):
        _verify(dk.link_status_message(KEY.device_id, first["ts"], first["seq"], "up"), first["sig"])
    with pytest.raises(ValueError):
        await link_status.report(session, "sideways")


@pytest.mark.asyncio
async def test_the_relay_only_ever_gets_the_hash_of_the_token():
    session = FakeSession()
    token = await link_status.issue_key(session)
    (path, body), = session.posts
    assert path == "/status-key" and len(token) >= 22 and token not in str(body)
    digest = hashlib.sha256(token.encode()).digest()
    assert dk.unb64url(body["key_hash"], 32) == digest
    _verify(dk.status_key_message(KEY.device_id, body["ts"], dk.unb64url(body["nonce"], 16), digest), body["sig"])
    with pytest.raises(link_status.RelayAuthError):
        await link_status.issue_key(FakeSession(status=409))


def _client(via_link: bool, manager) -> TestClient:
    app = FastAPI()
    app.state.phone_link = manager

    @app.middleware("http")
    async def mark(request, call_next):
        request.scope["via_link"] = via_link
        return await call_next(request)

    app.dependency_overrides[require_auth] = lambda: {"sub": "t"}
    app.include_router(link_status_routes.router, prefix="/api/v1")
    return TestClient(app)


def test_only_a_link_request_gets_a_token():
    async def issue():
        return "T" * 32

    manager = SimpleNamespace(available=True, issue_status_key=issue)
    assert _client(False, manager).post("/api/v1/link-status/key").status_code == 404
    answer = _client(True, manager).post("/api/v1/link-status/key")
    assert answer.status_code == 200 and answer.json() == {"token": "T" * 32}
    assert _client(True, None).post("/api/v1/link-status/key").status_code == 503


@pytest.mark.asyncio
async def test_the_manager_reports_signed_out_from_the_stored_sign_in(tmp_path):
    from src.core.catalog.token_store import CatalogSession, open_token_store
    from src.core.phone_link.manager import PhoneLinkManager

    session = FakeSession()
    me = SimpleNamespace(_session=session, _state_dir=tmp_path)
    await PhoneLinkManager.report_link_status(me)
    with open_token_store(tmp_path) as store:
        store.save(CatalogSession("owner", "a.b.c", 9999999999, "r", 9999999999, "github"))
    await PhoneLinkManager.report_link_status(me)
    assert [body["status"] for _, body in session.posts] == ["signed_out", "up"]
    await PhoneLinkManager.report_link_status(SimpleNamespace(_session=FakeSession(status=500), _state_dir=tmp_path))
