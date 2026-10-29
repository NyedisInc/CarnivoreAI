
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import native_device_routes
from src.api.auth import require_auth
from src.config import settings
from src.core import relay_keychain
from src.core.native_push import wiring
from src.core.native_push.store import MAX_DEVICES_PER_LINK_DEVICE
from src.core.notifications.destinations.secrets import DestinationSecrets

KEY = base64.urlsafe_b64encode(b"K" * 32).decode().rstrip("=")


class FakeKeychain:

    def __init__(self) -> None:
        self.items: Dict[str, str] = {}

    def read_state(self, service: str, account: str):
        value = self.items.get(account)
        return (relay_keychain.READ_OK, value) if value is not None else (relay_keychain.READ_ABSENT, None)

    def write(self, service: str, account: str, secret: str) -> None:
        self.items[account] = secret

    def delete(self, service: str, account: str) -> bool:
        return self.items.pop(account, None) is not None


class LinkScope:

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            device = headers.get(b"x-test-link-device")
            if device:
                scope["via_link"] = True
                scope["link_device"] = device.decode()
        await self.app(scope, receive, send)


def body(token: str = "ab" * 32, **extra) -> dict:
    return {"platform": "ios", "token": token, "environment": "sandbox", "bundle_id": "ai.carnivore.ios",
            "app_version": "1.0", "payload_key": KEY, **extra}


@pytest.fixture()
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path)
    app = FastAPI()
    app.include_router(native_device_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    keychain = FakeKeychain()
    app.state.native_push_secrets = DestinationSecrets(backend=keychain)
    paired = {"dev_a", "dev_b"}
    app.state.phone_link = SimpleNamespace(pairing=SimpleNamespace(
        devices=lambda: [SimpleNamespace(id=d) for d in paired]))
    return app, TestClient(LinkScope(app)), keychain, tmp_path


def as_device(device: str) -> dict:
    return {"x-test-link-device": device}


def test_device_comes_from_the_gate_never_the_body(rig) -> None:
    app, client, keychain, tmp = rig
    sent = {"device_id": "dev_b", "link_device": "dev_b"}
    made = client.post("/api/v1/native-devices", json=body(**sent), headers=as_device("dev_a"))
    assert made.status_code == 201 and made.json()["device_id"] == "dev_a"
    assert client.post("/api/v1/native-devices", json=body(), headers={}).status_code == 403
    row = wiring.store_for(app.state).list()[0]
    assert row["device_id"] == "dev_a"
    assert (tmp / "native_push_devices.json").stat().st_mode & 0o777 == 0o600
    assert KEY not in (tmp / "native_push_devices.json").read_text()
    assert list(keychain.items) == [row["id"]]
    again = client.post("/api/v1/native-devices", json=body(), headers=as_device("dev_a"))
    assert again.json()["id"] == row["id"] and len(wiring.store_for(app.state).list()) == 1


def test_the_key_and_token_are_in_no_response(rig, caplog) -> None:
    app, client, _, _ = rig
    texts = [client.post("/api/v1/native-devices", json=body(), headers=as_device("dev_a")).text,
             client.post("/api/v1/native-devices", json={**body(), "payload_key": "short"}, headers=as_device("dev_a")).text,
             client.get("/api/v1/native-devices").text]
    row_id = json.loads(texts[2])["devices"][0]["id"]
    texts.append(client.delete(f"/api/v1/native-devices/{row_id}").text)
    texts.append(client.delete(f"/api/v1/native-devices/{row_id}").text)
    for text in texts + [caplog.text]:
        assert KEY not in text and ("ab" * 32) not in text


def test_peer_token_is_401(rig, monkeypatch: pytest.MonkeyPatch) -> None:
    app, _, _, _ = rig
    app.dependency_overrides.clear()
    monkeypatch.setattr(type(settings), "load_auth_config", lambda self: SimpleNamespace(jwt_secret="s" * 40))
    peer = jwt.encode({"typ": "peer", "sub": "grant", "iid": "x", "exp": 4102444800}, "s" * 40, algorithm="HS256")
    client = TestClient(LinkScope(app))
    headers = {**as_device("dev_a"), "Authorization": f"Bearer {peer}"}
    assert client.post("/api/v1/native-devices", json=body(), headers=headers).status_code == 401
    assert client.get("/api/v1/native-devices", headers=headers).status_code == 401
    assert wiring.store_for(app.state).list() == []


def test_per_phone_cap_is_409(rig) -> None:
    app, client, _, _ = rig
    for i in range(MAX_DEVICES_PER_LINK_DEVICE):
        assert client.post("/api/v1/native-devices", json=body(token=f"{i:02x}" * 32), headers=as_device("dev_a")).status_code == 201
    over = client.post("/api/v1/native-devices", json=body(token="ff" * 32), headers=as_device("dev_a"))
    assert over.status_code == 409
    assert client.post("/api/v1/native-devices", json=body(token="ff" * 32), headers=as_device("dev_b")).status_code == 201


def test_revoke_cascades_to_rows_and_keys(rig) -> None:
    import asyncio

    app, client, keychain, _ = rig
    client.post("/api/v1/native-devices", json=body(), headers=as_device("dev_a"))
    client.post("/api/v1/native-devices", json=body(token="cd" * 32), headers=as_device("dev_b"))
    assert len(keychain.items) == 2
    assert asyncio.run(wiring.remove_for_device(app.state, "dev_a")) == 1
    left = client.get("/api/v1/native-devices").json()["devices"]
    assert [d["device_id"] for d in left] == ["dev_b"] and len(keychain.items) == 1


def test_revoke_cascade_drops_the_local_destination(rig, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    app, client, keychain, _ = rig
    dropped = []

    async def drop(state, row_id):
        dropped.append(row_id)

    monkeypatch.setattr(wiring, "drop_local_destination", drop)
    client.post("/api/v1/native-devices", json=body(), headers=as_device("dev_a"))
    row_id = client.get("/api/v1/native-devices").json()["devices"][0]["id"]
    asyncio.run(wiring.remove_for_device(app.state, "dev_a"))
    assert dropped == [row_id]


def test_payload_keys_use_their_own_service_and_legacy_keys_migrate() -> None:
    import asyncio
    from src.core.native_push.key_store import PayloadKeyStore

    class Keychain:
        def __init__(self) -> None:
            self.items: Dict[tuple, str] = {}

        def read_state(self, service, account):
            v = self.items.get((service, account))
            return (relay_keychain.READ_OK, v) if v is not None else (relay_keychain.READ_ABSENT, None)

        def write(self, service, account, secret):
            self.items[(service, account)] = secret

        def delete(self, service, account):
            return self.items.pop((service, account), None) is not None

    kc, row = Keychain(), "d_0123456789ab"
    fields = {wiring.KEY_FIELD: KEY}
    asyncio.run(DestinationSecrets(backend=kc).put(row, fields))
    store = PayloadKeyStore(backend=kc)
    assert asyncio.run(store.get(row)) == fields
    assert list(kc.items) == [(relay_keychain.NATIVE_PUSH_SERVICE, row)]
    asyncio.run(store.put("d_aaaaaaaaaaaa", fields))
    assert (relay_keychain.NATIVE_PUSH_SERVICE, "d_aaaaaaaaaaaa") in kc.items
    assert asyncio.run(store.delete(row)) and kc.items.keys() == {(relay_keychain.NATIVE_PUSH_SERVICE, "d_aaaaaaaaaaaa")}


def test_the_revoke_route_cascades(rig) -> None:
    from src.api import phone_link_routes
    from src.core.web_push.wiring import sender_for

    app, client, keychain, _ = rig

    async def revoke(device_id: str) -> bool:
        return True

    app.state.phone_link.revoke = revoke
    app.state.phone_link.available = True
    app.include_router(phone_link_routes.router, prefix="/api/v1")
    sender_for(app.state).__dict__["_transport"] = None
    client.post("/api/v1/native-devices", json=body(), headers=as_device("dev_a"))
    assert client.delete("/api/v1/phone-link/devices/dev_a").json() == {"revoked": True}
    assert client.get("/api/v1/native-devices").json() == {"devices": []} and keychain.items == {}
