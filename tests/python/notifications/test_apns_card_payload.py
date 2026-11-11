
from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.approvals import deliver
from src.core.approvals.inbox import ApprovalsInbox, item_id
from src.core.catalog import hosted_api
from src.core.native_push import payload_crypto
from src.core.native_push.apns_sender import ApnsSender
from src.core.native_push.store import NativeDeviceStore
from src.core.notifications import card_contract as cc, kind_specs
from src.core.notifications.cards import settle, sources
from src.core.notifications.contracts import NotifyEvent
from src.core.notifications.kinds import apns, registry
from src.core.notify_caps import store as caps_store
from src.core.relay_identity import device_key as dk

pytestmark = pytest.mark.asyncio

REPO = Path(__file__).resolve().parents[3]
VECTORS = {c["name"]: c for c in json.loads((REPO / "ios/Shared/TestVectors/notify_payload_vectors.json").read_text())["cases"]}
FIXTURES = REPO / "tests/fixtures/notify_cards"
CASE = VECTORS["yesno"]
ROW_ID, KEY = CASE["device_id"], bytes.fromhex(CASE["key"])
FP = "a" * 64


class FakeRelay:

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []

    async def __call__(self, base, method, path, *, json_body=None, bearer=None):
        self.requests.append(json_body)
        return hosted_api.HostedAnswer(200, {"ok": True})

    def opened(self, i: int) -> Dict[str, Any]:
        return json.loads(payload_crypto.open_blob(KEY, ROW_ID, base64.b64decode(self.requests[i]["payload"])))


class FakeSources:

    def __init__(self, dialog: Optional[Dict[str, Any]] = None) -> None:
        self.item = dialog

    async def dialog(self, session_id: str):
        return self.item

    def details_on(self, dest_id: str) -> bool:
        return True

    async def extra(self, event: Any):
        return {}


class _Secrets:
    async def get(self, row_id):
        return {"payload_key": base64.urlsafe_b64encode(KEY).decode().rstrip("=")}

    async def delete(self, row_id):
        return None


class _Session:
    dkey = dk.DeviceKey.from_seed(bytes([7]) * 32)

    async def key(self):
        return self.dkey

    async def account_bearer(self) -> str:
        return "acct-bearer"


@pytest.fixture
def rig(tmp_path: Path, monkeypatch):
    row = {"id": ROW_ID, "platform": "ios", "token": "ab" * 32, "environment": "sandbox", "bundle_id": "ai.carnivore.ios",
           "app_version": "1", "device_id": "dev_1", "created_at": "t", "last_seen": "t", "last_result": None}
    (tmp_path / "native_push_devices.json").write_text(json.dumps([row]))
    relay = FakeRelay()

    async def provide():
        return _Session()

    sender = ApnsSender(store=NativeDeviceStore(tmp_path), secrets=_Secrets(), session=provide,
                        control_url="https://api.carnivore.ai/v1/relay", call=relay, clock=lambda: 1000.0)
    monkeypatch.setattr(apns, "_provider", lambda: sender)
    monkeypatch.setattr(caps_store, "db_path", lambda: tmp_path / "notify_caps.db")
    settle._OPEN.clear()
    yield SimpleNamespace(relay=relay, cfg={"dest_id": kind_specs.apns_destination_id(ROW_ID)})
    sources.install(None)


def event(type_id: str, **kw: Any) -> NotifyEvent:
    base = dict(type_id=type_id, kind="PermissionRequest", title="t", ts=1.0, session_ref="api-docs", session_id="ses_1",
                tmux_name="carnivore_x", computer="studio", instance_key="toast:1:1", origin="local")
    return NotifyEvent(**{**base, **kw})


def permission_item() -> Dict[str, Any]:
    return {"source": "dialog", "session_id": "ses_1", "fingerprint": FP, "question": "run this?", "body": "npm run build in web/",
            "options": ["Yes", "Yes, and don't ask again", "No"], "rows": [], "plain_yes": None, "plain_no": None,
            "has_other": False, "multi_select": False, "question_total": None}


async def test_permission_ask_is_sealed_v2_with_a_minted_capability_and_settles_once(rig) -> None:
    sources.install(FakeSources(permission_item()))
    result = await registry.sender_for("apns").send(event("session.permission"), rig.cfg, {})
    assert result.ok and len(rig.relay.requests) == 1
    p = rig.relay.opened(0)
    assert p["v"] == 2 and p["kind"] == "permission" and p["lv"] == "t" and p["snd"] == "ask"
    assert all(k in p for k in cc.V1_KEYS) and len(cc.encode(p)) <= payload_crypto.MAX_PLAINTEXT_BYTES
    assert p["acts"] == [["opt.1", "Yes"], ["opt.2", "Yes, and don't ask again"], ["opt.3", "No"]]
    assert p["card"]["cmd"] == ["npm run build in web/"] and "more" not in p
    record = caps_store.get_store().find(p["cap"])
    assert record is not None and record.target == {"type": "dialog", "session": "ses_1", "fingerprint": FP}
    assert record.actions == {"opt.1": "Yes", "opt.2": "Yes, and don't ask again", "opt.3": "No"}

    inbox = ApprovalsInbox(lambda frame: None, debounce=0)
    open_now = {("dialog", item_id("ses_1", FP), FP)}
    inbox.register(SimpleNamespace(signature=lambda: frozenset(open_now)))
    inbox.on_lose_ids(settle.on_lost)
    inbox.refresh()
    assert len(rig.relay.requests) == 1
    open_now.clear()
    deliver.note_answered("ses_1", FP, deliver.SOURCE_OWNER)
    started = time.monotonic()
    inbox.refresh()
    while len(rig.relay.requests) < 2 and time.monotonic() - started < 10:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    assert len(rig.relay.requests) == 2 and time.monotonic() - started < 10
    s = rig.relay.opened(1)
    assert rig.relay.requests[1]["collapse_id"] == rig.relay.requests[0]["collapse_id"]
    assert s["lv"] == "p" and s["snd"] == "none" and "acts" not in s and "cap" not in s and "card" not in s
    assert s["settle"] == {"where": "computer", "agent": "api-docs", "working": False} and s["body"] == "answered on the computer"


def _inputs(name: str, fixture: Dict[str, Any]) -> tuple:
    card, type_id = fixture["card"], fixture["payload"]["type"]
    hint = {k: v for k, v in card.items() if k not in ("strip", "agent", "computer", "ts")}
    dialog = None
    if name in ("file", "image", "video"):
        hint = {"media": {**hint, "id": "0" * 32, "kind": name}}
    elif name in ("yesno", "choice", "permission"):
        dialog = {**permission_item(), "question": card.get("ask", "ok?"), "body": "\n".join(card.get("cmd", [])) or "x"}
        if name == "yesno":
            dialog.update(options=["Yes", "No"], plain_yes="Yes", plain_no="No", has_other=True)
        if name == "choice":
            dialog.update(options=[o[1] for o in card["opts"]], has_other=True)
    elif name == "swarm":
        hint = {**hint, "question_id": "q1", "positions": [["home", "a"], ["api-docs", "b"]]}
    elif name == "notice":
        hint = {"body": hint.get("body", "")}
    return event(type_id, card_hint=hint, session_ref=card["agent"], title=card.get("title", "t")), dialog


@pytest.mark.parametrize("name", list(cc.KINDS))
async def test_all_fifteen_kinds_open_and_validate_against_the_vectors_and_contract(rig, name: str) -> None:
    fixture = json.loads((FIXTURES / f"{name}.json").read_text())
    ev, dialog = _inputs(name, fixture)
    sources.install(FakeSources(dialog))
    assert (await registry.sender_for("apns").send(ev, rig.cfg, {})).ok
    p = rig.relay.opened(0)
    vector = json.loads(bytes.fromhex(VECTORS[name]["plaintext"]))
    assert p["kind"] == name == vector["kind"] and p["v"] == 2
    assert set(p) <= set(cc.PAYLOAD_KEYS) and set(p) <= set(vector) | {"more"}
    assert len(cc.encode(p)) <= payload_crypto.MAX_PLAINTEXT_BYTES
    cc.validate_card(name, p["card"]) if "card" in p else None
    assert not set(p.get("card", {})) & set(cc.FULL_ONLY.get(name, ()))
    assert [a[0] for a in p["acts"]][0] in {a.id for a in cc.ACTIONS[name]} | {"open"} or name in ("choice", "permission")
    assert ("cap" in p) == ("cap" in vector)
