
from __future__ import annotations

import base64
import importlib.util
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
import structlog

from src.core.catalog import hosted_api
from src.core.native_push import payload_crypto
from src.core.native_push.apns_sender import ApnsSender, push_base_url
from src.core.native_push.store import NativeDeviceStore
from src.core.notifications import kind_specs
from src.core.notifications.contracts import FailureClass, NotifyEvent
from src.core.notifications.kinds import apns, registry
from src.core.relay_identity import device_key as dk

pytestmark = pytest.mark.asyncio

REPO = Path(__file__).resolve().parents[3]
VECTORS = json.loads((REPO / "ios/Shared/TestVectors/apns_payload_vectors.json").read_text())["cases"]
TOKEN = "ab" * 32
_spec = importlib.util.spec_from_file_location("rc_crypto", REPO / "hosted/relay-control/rc_crypto.py")
rc_crypto = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc_crypto)


def ev(type_id: str = "session.finished", **kw: Any) -> NotifyEvent:
    d = dict(type_id=type_id, kind="Stop", title="x", ts=1.0, session_ref="my build", project="carnivore",
             computer="studio", link="https://studio.local/session/my-build", tmux_name="cloude_my-build")
    d.update(kw)
    return NotifyEvent(**d)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeSecrets:

    def __init__(self, items: Dict[str, Dict[str, str]]) -> None:
        self.items = items

    async def get(self, row_id: str) -> Optional[Dict[str, str]]:
        return self.items.get(row_id)

    async def delete(self, row_id: str) -> None:
        self.items.pop(row_id, None)


class FakeRelay:

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self.status, self.body = 200, {"ok": True}

    async def __call__(self, base: str, method: str, path: str, *, json_body=None, bearer=None):
        self.requests.append({"base": base, "method": method, "path": path, "body": json_body, "bearer": bearer})
        return hosted_api.HostedAnswer(self.status, dict(self.body))


class FakeSession:
    def __init__(self) -> None:
        self.dkey = dk.DeviceKey.from_seed(bytes([7]) * 32)

    async def key(self):
        return self.dkey

    async def account_bearer(self) -> str:
        return "acct-bearer"


@pytest.fixture
def rig(tmp_path: Path, monkeypatch):
    case = VECTORS[0]
    row_id = case["device_id"]
    row = {"id": row_id, "platform": "ios", "token": TOKEN, "environment": "sandbox", "bundle_id": "ai.carnivore.ios",
           "app_version": "1", "device_id": "dev_1", "created_at": "t", "last_seen": "t", "last_result": None}
    (tmp_path / "native_push_devices.json").write_text(json.dumps([row]))
    store = NativeDeviceStore(tmp_path)
    key_b64 = base64.urlsafe_b64encode(bytes.fromhex(case["key"])).decode().rstrip("=")
    secrets = FakeSecrets({row_id: {"payload_key": key_b64}})
    relay, clock, session, gone = FakeRelay(), Clock(), FakeSession(), []

    async def on_gone(rid: str) -> None:
        gone.append(rid)

    async def provide() -> FakeSession:
        return session

    sender = ApnsSender(store=store, secrets=secrets, session=provide, control_url="https://api.carnivore.ai/v1/relay",
                        on_gone=on_gone, call=relay, clock=clock)
    monkeypatch.setattr(apns, "_provider", lambda: sender)
    monkeypatch.setattr(payload_crypto, "os", SimpleNamespace(urandom=lambda n: bytes.fromhex(case["nonce"])[:n]))
    return SimpleNamespace(store=store, secrets=secrets, relay=relay, clock=clock, session=session, gone=gone,
                           cfg={"dest_id": kind_specs.apns_destination_id(row_id), "details": True}, case=case)


async def test_vectors_decrypt_with_plain_aesgcm_and_seal_reproduces_them() -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    for c in VECTORS:
        blob, key, aad = bytes.fromhex(c["ciphertext"]), bytes.fromhex(c["key"]), bytes.fromhex(c["aad"])
        assert blob[0] == 1 and blob[1:13] == bytes.fromhex(c["nonce"])
        assert AESGCM(key).decrypt(blob[1:13], blob[13:], aad) == bytes.fromhex(c["plaintext"])
        assert payload_crypto.seal(key, c["device_id"], bytes.fromhex(c["plaintext"]), nonce=bytes.fromhex(c["nonce"])) == blob
        with pytest.raises(ValueError):
            payload_crypto.open_blob(key, "d_000000000000", blob)


async def test_kind_sends_the_vector_ciphertext_signed_for_the_relay(rig) -> None:
    result = await registry.sender_for("apns").send(ev(details="secret words"), rig.cfg, {})
    assert result.ok and len(rig.relay.requests) == 1
    req = rig.relay.requests[0]
    assert (req["base"], req["method"], req["path"], req["bearer"]) == ("https://api.carnivore.ai/v1", "POST", "/push/apns", "acct-bearer")
    body = req["body"]
    assert base64.b64decode(body["payload"]) == bytes.fromhex(rig.case["ciphertext"])
    assert body["environment"] == "sandbox" and body["token"] == TOKEN and "secret words" not in json.dumps(body)
    ciphertext, nonce = base64.b64decode(body["payload"]), dk.unb64url(body["nonce"], 16)
    signed = rc_crypto.apns_message(rig.session.dkey.device_id, body["ts"], nonce, "sandbox", TOKEN, body["collapse_id"], ciphertext)
    assert rc_crypto.verify_ed25519(rig.session.dkey.raw_pub, dk.unb64url(body["sig"], 64), signed)
    assert len(body["collapse_id"]) == 24
    assert rig.store.list()[0]["last_result"]["status"] == 200


async def test_coalesces_per_device_type_and_instance(rig) -> None:
    send = registry.sender_for("apns").send
    assert (await send(ev(session_id="s1"), rig.cfg, {})).ok
    assert (await send(ev(session_id="s1"), rig.cfg, {})).ok and len(rig.relay.requests) == 1
    assert (await send(ev(session_id="s2"), rig.cfg, {})).ok and len(rig.relay.requests) == 2
    assert (await send(ev("session.died", session_id="s1"), rig.cfg, {})).ok and len(rig.relay.requests) == 3
    rig.clock.now += 11
    assert (await send(ev(session_id="s1"), rig.cfg, {})).ok and len(rig.relay.requests) == 4
    rig.relay.status = 502
    rig.clock.now += 11
    assert not (await send(ev(session_id="s1"), rig.cfg, {})).ok
    rig.relay.status = 200
    assert (await send(ev(session_id="s1"), rig.cfg, {})).ok and len(rig.relay.requests) == 6


async def test_410_deletes_the_row_and_its_key(rig) -> None:
    rig.relay.status, rig.relay.body = 410, {"code": "unregistered"}
    result = await registry.sender_for("apns").send(ev(), rig.cfg, {})
    assert result.failure is FailureClass.GONE
    assert rig.store.list() == [] and rig.secrets.items == {} and rig.gone == [rig.case["device_id"]]


async def test_unknown_device_missing_key_and_signed_out_never_raise(rig) -> None:
    assert (await registry.sender_for("apns").send(ev(), {"dest_id": "apns:d_nope"}, {})).failure is FailureClass.GONE
    rig.secrets.items.clear()
    assert (await registry.sender_for("apns").send(ev(), rig.cfg, {})).failure is FailureClass.INVALID and not rig.relay.requests


async def test_no_payload_key_or_token_in_any_log(rig, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    with structlog.testing.capture_logs() as captured:
        for status in (200, 502, 410):
            rig.relay.status = status
            rig.clock.now += 11
            await registry.sender_for("apns").send(ev(details="secret words"), rig.cfg, {})
    seen = json.dumps(captured, default=str) + caplog.text
    assert captured, "the sender logged nothing at all, so this check proved nothing"
    case = rig.case
    for secret in (case["key"], base64.urlsafe_b64encode(bytes.fromhex(case["key"])).decode().rstrip("="), "secret words",
                   "turn finished", TOKEN, base64.b64encode(bytes.fromhex(case["ciphertext"])).decode(), case["ciphertext"]):
        assert secret not in seen, secret


async def test_push_base_url_strips_the_relay_segment() -> None:
    assert push_base_url("https://api.carnivore.ai/v1/relay/") == "https://api.carnivore.ai/v1"
