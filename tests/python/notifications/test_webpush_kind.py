
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.core.notifications.contracts import FailureClass, NotifyEvent
from src.core.notifications.kind_specs import webpush_destination_id
from src.core.notifications.kinds import registry, webpush
from src.core.web_push.sender import COALESCE_SECONDS, PushSender
from tests.python.web_push.test_web_push import FCM, Clock, Phone, Service, _decrypt

pytestmark = pytest.mark.asyncio


def ev(type_id="session.finished", **kw) -> NotifyEvent:
    d = dict(type_id=type_id, kind="Stop", title="x", ts=1.0, session_ref="my build", project="carnivore",
             computer="studio", link="https://studio.local/session/my-build", tmux_name="cloude_my-build")
    d.update(kw)
    return NotifyEvent(**d)


@pytest.fixture
def rig(tmp_path: Path, monkeypatch):
    service, clock, phone = Service(), Clock(), Phone()
    sender = PushSender(tmp_path, tmp_path / "config.json", transport=service.transport(), clock=clock)
    sub = sender.store.add(FCM, phone.p256dh, phone.auth_b64, "dev_1")
    monkeypatch.setattr(webpush, "_provider", lambda: sender)
    cfg = {"dest_id": webpush_destination_id(sub["id"]), "details": True}
    return service, clock, phone, sender, sub, cfg


async def test_typed_payload_is_decryptable_and_fixed(rig) -> None:
    service, _, phone, _, _, cfg = rig
    r = await registry.sender_for("webpush").send(ev(details="secret words"), cfg, {})
    assert r.ok
    req = service.requests[0]
    assert req.headers["Topic"] != "approval" and len(req.headers["Topic"]) <= 32
    got = json.loads(_decrypt(req.content, phone.private, phone.auth))
    assert got == {"title": "turn finished", "body": "my build (carnivore) on studio finished its turn.",
                   "path": "/session/cloude_my-build"}
    assert "secret words" not in json.dumps(got) and "https://" not in json.dumps(got)


@pytest.mark.parametrize("type_id", ["session.question", "session.permission", "session.plan_approval"])
async def test_ask_types_link_to_the_approvals_popup_not_the_terminal(rig, type_id) -> None:
    service, _, phone, _, _, cfg = rig
    await webpush.WebPushSender().send(ev(type_id=type_id, kind="PermissionRequest", session_id="ses_1"), cfg, {})
    got = json.loads(_decrypt(service.requests[0].content, phone.private, phone.auth))
    assert got["path"] == "/?approvals=ses_1"


async def test_other_types_keep_the_session_path(rig) -> None:
    service, _, phone, _, _, cfg = rig
    await webpush.WebPushSender().send(ev(type_id="session.attention", kind="Notification", session_id="ses_1"), cfg, {})
    assert json.loads(_decrypt(service.requests[0].content, phone.private, phone.auth))["path"] == "/session/cloude_my-build"


async def test_path_falls_back_to_root_without_a_session(rig) -> None:
    service, _, phone, _, _, cfg = rig
    await webpush.WebPushSender().send(ev(session_ref="", tmux_name=None), cfg, {})
    assert json.loads(_decrypt(service.requests[0].content, phone.private, phone.auth))["path"] == "/"


@pytest.mark.parametrize("status", [404, 410])
async def test_gone_prunes_the_subscription(rig, status) -> None:
    service, _, _, sender, _, cfg = rig
    service.status = status
    r = await webpush.WebPushSender().send(ev(), cfg, {})
    assert r.failure is FailureClass.GONE and sender.store.list() == []


async def test_other_failures_keep_the_subscription_and_classify(rig) -> None:
    service, _, _, sender, _, cfg = rig
    service.status = 503
    r = await webpush.WebPushSender().send(ev(), cfg, {})
    assert r.failure is FailureClass.SERVER and len(sender.store.list()) == 1
    assert sender.store.list()[0]["last_result"]["status"] == 503


async def test_coalesced_per_subscription_and_type(rig) -> None:
    service, clock, _, sender, _, cfg = rig
    s = webpush.WebPushSender()
    assert (await s.send(ev(), cfg, {})).ok and (await s.send(ev(), cfg, {})).ok
    assert len(service.requests) == 1
    await s.send(ev("session.question"), cfg, {})
    assert len(service.requests) == 2
    clock.now += COALESCE_SECONDS + 1
    await s.send(ev(), cfg, {})
    assert len(service.requests) == 3
    other = sender.store.add("https://fcm.googleapis.com/fcm/send/zzz", rig[2].p256dh, rig[2].auth_b64)
    await s.send(ev(), {"dest_id": webpush_destination_id(other["id"])}, {})
    assert len(service.requests) == 4


async def test_unknown_subscription_and_missing_sender(rig, monkeypatch) -> None:
    r = await webpush.WebPushSender().send(ev(), {"dest_id": "webpush:nope"}, {})
    assert r.failure is FailureClass.GONE
    monkeypatch.setattr(webpush, "_provider", None)
    assert (await webpush.WebPushSender().send(ev(), {"dest_id": "webpush:x"}, {})).failure is FailureClass.INVALID
    assert (await webpush.WebPushSender().send(ev(), {"dest_id": "d_0123456789ab"}, {})).failure is FailureClass.INVALID


async def test_old_fixed_payload_path_still_works(rig) -> None:
    service, _, phone, sender, _, _ = rig
    out = await sender.notify(force=True)
    assert [o["status"] for o in out] == [201]
    assert json.loads(_decrypt(service.requests[0].content, phone.private, phone.auth)) == {
        "title": "carnivore", "body": "approval needed"}
    assert service.requests[0].headers["Topic"] == "approval"


async def test_two_sessions_needs_you_within_window_both_send(rig) -> None:
    service, _, _, _, _, cfg = rig
    s = webpush.WebPushSender()
    await s.send(ev("session.question", session_id="ses_a"), cfg, {})
    await s.send(ev("session.question", session_id="ses_b"), cfg, {})
    await s.send(ev("session.question", session_id="ses_a"), cfg, {})
    assert len(service.requests) == 2
    assert service.requests[0].headers["Topic"] != service.requests[1].headers["Topic"]


async def test_a_failed_push_is_not_stamped_so_its_retry_really_sends(rig) -> None:
    service, clock, _, _, _, cfg = rig
    s = webpush.WebPushSender()
    service.status = 503
    assert (await s.send(ev(), cfg, {})).failure is FailureClass.SERVER
    service.status = 201
    clock.now += 1
    assert (await s.send(ev(), cfg, {})).ok
    assert len(service.requests) == 2
    assert (await s.send(ev(), cfg, {})).ok
    assert len(service.requests) == 2
