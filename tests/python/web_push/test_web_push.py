
from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.core.approvals.inbox import ApprovalsInbox
from src.core.web_push import vapid
from src.core.web_push.encrypt import encrypt_payload
from src.core.web_push.endpoints import endpoint_allowed
from src.core.web_push.sender import FIXED_PAYLOAD, PushSender
from src.core.web_push.store import SubscriptionStore

FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def _b(text: str) -> bytes:
    return vapid.b64url_decode(text)


def _private_from_scalar(text: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(_b(text), "big"), ec.SECP256R1())


def test_rfc8291_section5_vector() -> None:
    body = encrypt_payload(
        b"When I grow up, I want to be a watermelon",
        _b("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"),
        _b("BTBZMqHH6r4Tts7J_aSIgg"),
        salt=_b("DGv6ra1nlYgDCS1FRnbzlw"),
        as_private=_private_from_scalar("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"),
    )
    assert vapid.b64url(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIg"
        "Dll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBS"
        "t2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )


def _decrypt(body: bytes, ua_private: ec.EllipticCurvePrivateKey, auth: bytes) -> bytes:
    salt, (_, idlen) = body[:16], struct.unpack(">IB", body[16:21])
    as_public, sealed = body[21:21 + idlen], body[21 + idlen:]
    ua_public = ua_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = ua_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))

    def hk(s: bytes, ikm: bytes, info: bytes, n: int) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=n, salt=s, info=info).derive(ikm)

    ikm = hk(auth, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    plain = AESGCM(hk(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(
        hk(salt, ikm, b"Content-Encoding: nonce\x00", 12), sealed, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_vapid_jwt_verifies_and_claims(tmp_path: Path) -> None:
    key = vapid.load_or_create_key(tmp_path)
    assert (tmp_path / vapid.KEY_FILE).stat().st_mode & 0o777 == 0o600
    assert vapid.public_key_b64(tmp_path) == vapid.b64url(vapid.public_key_bytes(key))
    token = vapid.sign_jwt(key, "https://fcm.googleapis.com", vapid.DEFAULT_SUBJECT, now=1_000_000, lifetime=10**9)
    head, body, sig = token.split(".")
    raw = _b(sig)
    key.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                            f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    claims = json.loads(_b(body))
    assert claims == {"aud": "https://fcm.googleapis.com", "exp": 1_000_000 + 12 * 3600, "sub": "https://carnivore.ai"}
    assert json.loads(_b(head)) == {"typ": "JWT", "alg": "ES256"}


def test_subject_config(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    assert vapid.subject_from_config(cfg) == vapid.DEFAULT_SUBJECT
    cfg.write_text(json.dumps({"web_push": {"subject": "mailto:me@example.com"}}))
    assert vapid.subject_from_config(cfg) == "mailto:me@example.com"
    cfg.write_text(json.dumps({"web_push": {"subject": "http://insecure"}}))
    assert vapid.subject_from_config(cfg) == vapid.DEFAULT_SUBJECT


@pytest.mark.parametrize("endpoint,ok", [
    (FCM, True),
    ("https://web.push.apple.com/QAbc", True),
    ("https://api.push.apple.com/3/device/x", True),
    ("https://updates.push.services.mozilla.com/wpush/v2/x", True),
    ("http://fcm.googleapis.com/x", False),
    ("https://127.0.0.1/x", False),
    ("https://localhost/x", False),
    ("https://example.net/fcm.googleapis.com", False),
    ("https://fcm.googleapis.com.example.net/x", False),
    ("https://evilpush.apple.com/x", False),
    ("https://user:pw@fcm.googleapis.com/x", False),
    ("https://fcm.googleapis.com:8443/x", False),
    ("https://fcm.googleapis.com\n/x", False),
    ("https://fcm.googleapis.com/x y", False),
    ("https://fcm.googleapis.com:443/x", False),
    ("https://fcm.googleapis.com\\@example.net/x", False),
    ("", False),
])
def test_endpoint_allow_list(endpoint: str, ok: bool) -> None:
    assert endpoint_allowed(endpoint) is ok


class Phone:

    def __init__(self) -> None:
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.auth = bytes(range(16))
        self.p256dh = vapid.b64url(self.private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        self.auth_b64 = vapid.b64url(self.auth)


class Service:

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.requests: List[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status)
        return httpx.MockTransport(handle)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _sender(tmp_path: Path, service: Service, clock: Clock) -> PushSender:
    return PushSender(tmp_path, tmp_path / "config.json", transport=service.transport(), clock=clock)


def test_send_rate_limit_and_headers(tmp_path: Path) -> None:
    service, clock, phone = Service(), Clock(), Phone()
    sender = _sender(tmp_path, service, clock)
    sub = sender.store.add(FCM, phone.p256dh, phone.auth_b64, "dev_1")
    first = asyncio.run(sender.notify())
    assert [r["status"] for r in first] == [201]
    request = service.requests[0]
    assert request.headers["TTL"] and request.headers["Urgency"] == "high" and request.headers["Topic"] == "approval"
    assert request.headers["Content-Encoding"] == "aes128gcm"
    assert request.headers["Authorization"].startswith("vapid t=") and ", k=" in request.headers["Authorization"]
    assert asyncio.run(sender.notify()) == []
    clock.now += 59
    assert asyncio.run(sender.notify()) == []
    clock.now += 2
    assert len(asyncio.run(sender.notify())) == 1
    assert len(service.requests) == 2
    assert len(asyncio.run(sender.notify(force=True))) == 1
    row = sender.store.list()[0]
    assert row["id"] == sub["id"] and row["last_result"]["status"] == 201 and row["last_result"]["at"]


def test_410_and_404_delete_and_other_errors_are_recorded(tmp_path: Path) -> None:
    clock, phone = Clock(), Phone()
    for gone in (410, 404):
        sender = _sender(tmp_path, Service(gone), clock)
        sender.store.add(FCM, phone.p256dh, phone.auth_b64)
        asyncio.run(sender.notify())
        assert sender.store.list() == []
    sender = _sender(tmp_path, Service(503), clock)
    sender.store.add(FCM, phone.p256dh, phone.auth_b64)
    asyncio.run(sender.notify())
    assert sender.store.list()[0]["last_result"]["status"] == 503


def test_stored_endpoint_off_the_allow_list_is_never_called(tmp_path: Path) -> None:
    service, phone = Service(), Phone()
    sender = _sender(tmp_path, service, Clock())
    sender.store.add("https://127.0.0.1/internal", phone.p256dh, phone.auth_b64)
    assert asyncio.run(sender.notify()) == []
    assert service.requests == [] and sender.store.list() == []


def test_remove_for_device(tmp_path: Path) -> None:
    store, phone = SubscriptionStore(tmp_path), Phone()
    store.add(FCM, phone.p256dh, phone.auth_b64, "dev_1")
    store.add(FCM + "2", phone.p256dh, phone.auth_b64, "dev_2")
    assert store.remove_for_device("dev_1") == 1
    assert [r["device_id"] for r in store.list()] == ["dev_2"]
    assert (tmp_path / "web_push_subscriptions.json").stat().st_mode & 0o777 == 0o600


CANARY = "CANARY-secret-question-text"


class FakeProvider:

    def __init__(self) -> None:
        self.ids: List[str] = []

    def signature(self) -> frozenset:
        return frozenset(("dialog", i, "fp") for i in self.ids)

    async def items(self) -> List[Dict[str, Any]]:
        return [{"id": i, "question": CANARY, "session_name": CANARY, "body": CANARY} for i in self.ids]


def test_the_untyped_test_push_payload_is_fixed_and_carries_no_session_text(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, phone = Service(), Phone()
        sender = _sender(tmp_path, service, Clock())
        sender.store.add(FCM, phone.p256dh, phone.auth_b64)
        assert not hasattr(sender, "on_inbox_gain")
        await sender.notify(force=True)
        assert len(service.requests) == 1
        request = service.requests[0]
        assert CANARY.encode() not in request.content
        assert _decrypt(request.content, phone.private, phone.auth) == FIXED_PAYLOAD
        assert json.loads(FIXED_PAYLOAD) == {"title": "carnivore", "body": "approval needed"}
    asyncio.run(scenario())


def test_routes_refuse_bad_endpoint_and_hide_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import web_push_routes
    from src.api.auth import require_auth
    from src.config import settings
    from src.core.web_push.wiring import sender_for

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path)
    app = FastAPI()
    app.include_router(web_push_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    sender_for(app.state).__dict__["_transport"] = Service().transport()
    phone = Phone()
    client = TestClient(app)
    good = {"endpoint": FCM, "keys": {"p256dh": phone.p256dh, "auth": phone.auth_b64}}
    assert client.post("/api/v1/push/subscriptions", json={**good, "endpoint": "https://127.0.0.1/x"}).status_code == 422
    assert client.post("/api/v1/push/subscriptions", json={**good, "keys": {"p256dh": "AAAA", "auth": phone.auth_b64}}).status_code == 422
    created = client.post("/api/v1/push/subscriptions", json=good)
    assert created.status_code == 201
    listed = client.get("/api/v1/push/subscriptions").json()["subscriptions"]
    assert listed[0]["service"] == "fcm.googleapis.com" and "abc123" not in json.dumps(listed) and phone.auth_b64 not in json.dumps(listed)
    assert client.get("/api/v1/push/vapid-public-key").json()["key"] == vapid.public_key_b64(tmp_path)
    sent = client.post("/api/v1/push/test").json()["sent"]
    assert sent[0]["status"] == 201
    assert client.delete(f"/api/v1/push/subscriptions/{listed[0]['id']}").status_code == 204
    assert client.delete(f"/api/v1/push/subscriptions/{listed[0]['id']}").status_code == 404


def test_two_gains_at_once_send_once(tmp_path: Path) -> None:
    service, phone = Service(), Phone()
    sender = _sender(tmp_path, service, Clock())
    sender.store.add(FCM, phone.p256dh, phone.auth_b64)

    async def go() -> None:
        await asyncio.gather(sender.notify(), sender.notify())
    asyncio.run(go())
    assert len(service.requests) == 1


def test_bad_endpoint_and_malformed_row_do_not_poison_the_rest(tmp_path: Path) -> None:
    service, phone = Service(), Phone()
    sender = _sender(tmp_path, service, Clock())
    sender.store.add(FCM, phone.p256dh, phone.auth_b64)
    sender.store.add("https://fcm.googleapis.com\n/x", phone.p256dh, phone.auth_b64)
    path = tmp_path / "web_push_subscriptions.json"
    rows = json.loads(path.read_text())
    rows += ["not a dict", {"id": "x"}]
    path.write_text(json.dumps(rows))
    sent = asyncio.run(sender.notify(force=True))
    assert len(service.requests) == 1 and [r["status"] for r in sent] == [201]
    assert [r["endpoint"] for r in sender.store.list()] == [FCM]


def test_restart_keeps_the_60s_floor(tmp_path: Path) -> None:
    phone = Phone()
    first = _sender(tmp_path, Service(), Clock())
    first.store.add(FCM, phone.p256dh, phone.auth_b64)
    asyncio.run(first.notify())
    service = Service()
    second = _sender(tmp_path, service, Clock())
    assert asyncio.run(second.notify()) == [] and service.requests == []


def test_test_button_cooldown(tmp_path: Path) -> None:
    service, clock, phone = Service(), Clock(), Phone()
    sender = _sender(tmp_path, service, clock)
    sender.store.add(FCM, phone.p256dh, phone.auth_b64)
    assert asyncio.run(sender.notify_test()) is not None
    assert asyncio.run(sender.notify_test()) is None
    clock.now += 6
    assert asyncio.run(sender.notify_test()) is not None


def test_throwing_listener_does_not_abort_refresh() -> None:
    provider = FakeProvider()
    inbox = ApprovalsInbox(lambda frame: None, debounce=0)
    inbox.register(provider)
    seen: List[int] = []

    def boom() -> None:
        raise RuntimeError("x")
    inbox.on_gain(boom)
    inbox.on_gain(lambda: seen.append(1))
    provider.ids = ["dlg:a"]
    assert inbox.refresh() is True and seen == [1]


def test_new_subscription_is_seeded_once(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace
    from src.api import web_push_routes as routes
    seeded: List[tuple] = []

    class Dest:
        async def seed_destination_ticks(self, dest_id: str, kind: str) -> None:
            seeded.append((dest_id, kind))

    sender = PushSender(tmp_path, tmp_path / "config.json")
    monkeypatch.setattr(routes, "sender_for", lambda _s: sender)
    monkeypatch.setattr(routes, "get_service", lambda _s: SimpleNamespace(destinations=Dest()))
    phone = Phone()
    body = routes.SubscribeBody(endpoint=FCM, keys=routes.Keys(p256dh=phone.p256dh, auth=phone.auth_b64))
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()), scope={})
    first = asyncio.run(routes.add_subscription(body, req))
    asyncio.run(routes.add_subscription(body, req))
    assert seeded == [(f"webpush:{first['id']}", "webpush")]
