
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
import pytest_asyncio

from src.config import settings
from src.core.attention_wiring import build_attention_watcher
from src.core.federation import peer_event_stream
from src.core.notifications import contracts, doc_model, install
from src.core.notifications.destinations.secrets import DestinationSecrets
from src.core.notifications.destinations.service import NotificationService
from src.core.notifications.kinds import registry
from src.core.notifications.settings_doc import ticks
from src.core.notifications.sources import toast as toast_source
from src.core.web_push.sender import PushSender
from tests.python.notification_destinations.test_install_boot import FailableKeychain
from tests.python.notifications.engine_fakes import NOON, FakeSender
from tests.python.web_push.test_web_push import FCM, Clock, Phone, Service, _decrypt
from tests.test_attention_wiring import (  # noqa: F401
    RecordingManager, busy_pair, done_pair, gathered_file_tiers, no_real_pulls,
)

pytestmark = pytest.mark.asyncio
SLACK_URL = "https://hooks.slack.com/services/T/B/X"


class EmittingManager(RecordingManager):

    def __init__(self, *args: Any, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self._registry = SimpleNamespace(
            sessions={sid: SimpleNamespace(tmux_session=name) for sid, name in self._names.items()},
            backends=self._registry.backends, listable_ids=lambda: list(self._names))
        self._identity_for_live_name = lambda name: {"project_name": "api"}
        self._label_for_tmux_name = lambda name: name

    def record_toast(self, session_id, kind, title, body=None, *, notify_type=None):
        toast = super().record_toast(session_id, kind, title, body, notify_type=notify_type)
        toast_source.emit_event(self, toast)
        return toast


class Wired:

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)

    async def settle(self) -> None:
        engine = self.handle.engine
        await asyncio.sleep(0)
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline and any(
                t.get_coro().__qualname__.endswith("NotifyEngine.handle") for t in list(engine._tasks)):
            await asyncio.sleep(0.01)
        await engine.join()

    async def emit(self, type_id: str, n: int, *, session: str = "ses_1", tmux: str = "cloude_api") -> None:
        contracts.emit(contracts.NotifyEvent(
            type_id=type_id, kind="Stop", title="t", ts=NOON, instance_key=f"e{n}", session_id=session,
            tmux_name=tmux))
        await self.settle()


@pytest_asyncio.fixture()
async def wired(tmp_path: Path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"config_version": 1}))
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path / "state"))
    service, phone = Service(), Phone()
    push = PushSender(tmp_path, config, transport=service.transport(), clock=Clock())
    svc = NotificationService(config, subscriptions=push.store.list)
    svc.destinations._secrets = svc.secrets = DestinationSecrets(backend=FailableKeychain())
    app_state = SimpleNamespace(notification_service=svc, web_push_sender=push)
    fake, real = FakeSender(), registry.sender_for
    monkeypatch.setattr(registry, "sender_for", lambda kind: real(kind) if kind == "webpush" else fake)
    muted: set = set()
    manager = SimpleNamespace(notification_policy_for=lambda sid: SimpleNamespace(suppresses=sid in muted))
    handle = await install.install(app_state, manager)
    assert handle.engine is not None
    handle.engine._clock = lambda: NOON
    created = await svc.destinations.create("slack", "team", {}, {"url": SLACK_URL})
    dest_id = created.destination["id"]
    await asyncio.to_thread(svc.docs.update, lambda d, me: doc_model.set_global(
        d, doc_model.extra_path(dest_id, "reminder"), 0, me))
    try:
        yield Wired(handle=handle, svc=svc, fake=fake, push=push, service=service, phone=phone, muted=muted,
                    dest_id=dest_id)
    finally:
        await install.uninstall(handle)


async def test_one_real_watcher_stop_gives_exactly_one_delivery(wired: Wired, no_real_pulls) -> None:
    manager = EmittingManager({"ses_a": "cloude_a"}, {"cloude_a": done_pair()})
    watcher = build_attention_watcher(manager, tick_seconds=0.0)
    await watcher.tick_once()
    manager._reads["cloude_a"] = busy_pair()
    await watcher.tick_once()
    manager._reads["cloude_a"] = done_pair()
    for _ in range(3):
        await watcher.tick_once()
    await wired.settle()
    assert [t.notify_type for t in manager.toasts] == ["session.finished"]
    assert len(wired.fake.calls) == 1
    assert wired.fake.calls[0][0].type_id == "session.finished"


async def test_a_needs_you_event_passes_quiet_hours_and_away_while_finished_does_not(wired: Wired) -> None:
    quiet = {"start": "11:00", "end": "13:00"}
    for extra, value in (("quiet", quiet), ("away", True)):
        await asyncio.to_thread(wired.svc.docs.update, lambda d, me, e=extra, v=value: doc_model.set_global(
            d, doc_model.extra_path(wired.dest_id, e), v, me))
    await wired.emit("session.permission", 1)
    assert [c[0].type_id for c in wired.fake.calls] == ["session.permission"]
    await wired.emit("session.finished", 2)
    assert [c[0].type_id for c in wired.fake.calls] == ["session.permission"]


async def test_the_session_mute_and_the_pause_switch_stop_outside_delivery(wired: Wired) -> None:
    await wired.emit("session.permission", 1)
    assert len(wired.fake.calls) == 1
    wired.muted.add("ses_1")
    await wired.emit("session.permission", 2)
    assert len(wired.fake.calls) == 1
    wired.muted.clear()
    await asyncio.to_thread(ticks.set_paused, wired.svc.docs, True)
    await wired.emit("session.permission", 3)
    assert len(wired.fake.calls) == 1
    await asyncio.to_thread(ticks.set_paused, wired.svc.docs, False)
    await wired.emit("session.permission", 4)
    assert len(wired.fake.calls) == 2


async def test_a_peer_origin_event_is_refused_through_the_installed_wiring(wired: Wired) -> None:
    frame = peer_event_stream.translate(
        {"type": "toast.new", "toast": {"id": "t1", "session_id": "ses_1", "session_name": "api",
                                        "kind": "PermissionRequest", "title": "needs you", "body": "run ls?"}},
        "peer-ab12")
    peer_event_stream.offer_to_engine(frame)
    await wired.settle()
    assert wired.fake.calls == []


async def test_a_web_push_device_gets_the_typed_payload_through_the_installed_sender(wired: Wired) -> None:
    sub = wired.push.store.add(FCM, wired.phone.p256dh, wired.phone.auth_b64, "dev_1")
    await wired.svc.destinations.seed_destination_ticks(f"webpush:{sub['id']}", "webpush")
    await wired.emit("session.permission", 1)
    assert len(wired.service.requests) == 1
    body = json.loads(_decrypt(wired.service.requests[0].content, wired.phone.private, wired.phone.auth))
    assert set(body) == {"title", "body", "path"} and body["title"] and body["body"]
    assert body["path"] == "/?approvals=ses_1"
