
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core import relay_keychain
from src.core.messaging import contract, ddl, message_store, notices, runtime, store
from src.core.messaging.client import ProviderError
from src.core.messaging.runtime import MessagingRuntime
from src.core.messaging.secrets import MessagingSecrets, ProviderSecrets, match_of

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "approvals"
JOE = "+15555550100"
STRANGER = "+15555550199"
CONV = "any;-;+15555550100"
OTHER_CONV = "any;-;+15555550111"
UUID_A = "aaaaaaaa-1111-4111-8111-111111111111"
UUID_B = "bbbbbbbb-2222-4222-8222-222222222222"
TEST_SERVICE = "ai.carnivore.test.messaging"


def screen(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


class FakeKeychain:

    def __init__(self) -> None:
        self.items: Dict[tuple, str] = {}

    def read_state(self, service, account):
        value = self.items.get((service, account))
        return (relay_keychain.READ_OK, value) if value else (relay_keychain.READ_ABSENT, None)

    def write(self, service, account, secret):
        self.items[(service, account)] = secret

    def delete(self, service, account):
        return self.items.pop((service, account), None) is not None


class FakeProvider:

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []
        self.listed = [contract.ConversationEntry(CONV, "joe", (JOE,), True),
                       contract.ConversationEntry(OTHER_CONV, "someone", ("+1",), False)]
        self.fail_send: Optional[str] = None
        self.receive = True

    async def capabilities(self) -> contract.Capabilities:
        return contract.parse_capabilities({
            "cpp": 1, "provider": "imsg-bridge", "version": "1.0.0", "send": True, "receive": self.receive,
            "threading": "available", "max_identity": "strong", "max_text_chars": 2000,
            "stream": {"ws": True, "routable_filter": True, "retained_events": 50000},
            "health": {"send_ready": True, "receive_ready": True, "detail": "ok"}})

    async def conversations(self):
        return tuple(self.listed)

    async def send(self, conversation, text, *, reply_to, client_ref):
        if self.fail_send:
            raise ProviderError(self.fail_send)
        self.sent.append({"conversation": conversation, "text": text, "client_ref": client_ref})
        return contract.SendResult(f"g-{len(self.sent)}", 1_800_000_000.0, "sent")

    async def events_page(self, after, limit=200):
        return contract.EventsPage()


class FakeManager:

    def __init__(self) -> None:
        self.infos: Dict[str, Any] = {}
        self.commands: List[str] = []

    async def get_session_info(self, session_id=None):
        return self.infos.get(session_id)

    async def send_command(self, command, session_id=None):
        self.commands.append(command)
        return True

    def tmux_socket_name(self):
        return "cloude-test-never-used"


def info(session_id: str, *, row_id: int, status: str = "idle", gate: str = "ready", family: str = "claude",
         name: str = "ledgerbot") -> SimpleNamespace:
    return SimpleNamespace(activity_status=status, startup_gate=gate, agent_family=family, tmux_session=f"cloude_{name}",
                           session_row_id=row_id, label=name, claude_title=None, session=SimpleNamespace(id=session_id))


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "cloude.db"

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    with connect() as conn:
        ddl.apply_v73(conn)
        ddl.apply_v92(conn)
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT)")
        conn.execute("INSERT INTO sessions (id, session_uuid) VALUES (1, ?), (2, ?)", (UUID_A, UUID_B))
    monkeypatch.setattr(store, "_conn", connect)
    pushed: List[str] = []
    monkeypatch.setattr(store.resource_push, "notify", lambda topic: pushed.append(topic))
    return SimpleNamespace(path=path, connect=connect, pushed=pushed)


@pytest.fixture
def world(db, monkeypatch):
    from src.api import channel_delivery
    from src.core.approvals import dialog_gate
    from src.core.messaging import delivery

    keychain = FakeKeychain()
    provider = FakeProvider()
    manager = FakeManager()
    manager.infos["ses_a"] = info("ses_a", row_id=1, name="ledgerbot")
    manager.infos["ses_b"] = info("ses_b", row_id=2, name="infra")
    app = SimpleNamespace(state=SimpleNamespace(session_manager=manager))
    rt = MessagingRuntime(app, secrets=MessagingSecrets(backend=keychain, service=TEST_SERVICE),
                          client_factory=lambda row, secrets: provider, start_streams=False)
    app.state.messaging = rt
    secrets = ProviderSecrets(base_url="http://198.51.100.16:8787", token="tok-not-real", owner_senders=(JOE,),
                              match_key="k" * 64)
    pid = "p_0123456789ab"
    asyncio.run(rt.secrets.save(pid, secrets))
    caps = asyncio.run(provider.capabilities()).as_json()
    store.create_provider(provider_id=pid, name="imessage", owner_label="joe", allow_private=True,
                          allow_plain_http=True, capabilities=caps)
    conv_id = "c_0123456789ab"
    store.create_conversation(conversation_id=conv_id, provider_id=pid, label="joe",
                              match_key=match_of(secrets.match_key, CONV))
    asyncio.run(rt.secrets.save(pid, secrets.with_conversation(conv_id, CONV)))
    asyncio.run(rt.load(pid))

    cards = {UUID_A: {"id": "ses_a", "name": "ledgerbot", "session_uuid": UUID_A, "status": "idle"},
             UUID_B: {"id": "ses_b", "name": "infra", "session_uuid": UUID_B, "status": "idle"}}

    async def fake_cards(_app):
        return dict(cards)

    monkeypatch.setattr(delivery, "session_cards", fake_cards)
    screens: Dict[str, str] = {"cloude_ledgerbot": "> \n", "cloude_infra": "> \n"}

    async def capture(_manager, tmux_name):
        return screens.get(tmux_name)

    monkeypatch.setattr(dialog_gate, "_default_capture", capture)
    pasted: List[Dict[str, Any]] = []

    async def fake_deliver(request, session_id, text, meta=None, *, fresh_dialog_check=False):
        assert fresh_dialog_check is True, "every messaging delivery must ask the fresh dialog check in the lock"
        if await dialog_gate.dialog_verdict(request.app, session_id) != dialog_gate.CLEAR:
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail={"code": "pane_dialog_open"})
        pasted.append({"session_id": session_id, "text": text})
        return channel_delivery.DeliveryResponse(pasted_bytes=len(text), submitted=True, delivered_via="paste")

    monkeypatch.setattr(channel_delivery, "deliver_through_gates", fake_deliver)
    alerts: List[Dict[str, Any]] = []
    monkeypatch.setattr(runtime.alert_service, "raise_alert", lambda key, **kw: alerts.append({"key": key, **kw}))
    woken: List[str] = []
    rt.wake = lambda uuid: woken.append(uuid)
    notices.copy.cache_clear()
    return SimpleNamespace(rt=rt, provider=provider, manager=manager, keychain=keychain, conv_id=conv_id, pid=pid,
                           pasted=pasted, alerts=alerts, woken=woken, cards=cards, screens=screens, app=app)


def bind(world, uuid: str, direction: str = "both", default: bool = False) -> dict:
    return store.create_binding(conversation_id=world.conv_id, session_uuid=uuid, direction=direction,
                                is_default=default, created_by="owner")


def received(event_id: int, text: str, *, message_id: Optional[str] = None, sender: str = JOE,
             identity: str = "strong", conversation: str = CONV, sent_at: Optional[str] = None,
             kind: str = "message.received", in_reply_to: Optional[str] = None) -> contract.Event:
    if sent_at is None:
        from datetime import datetime, timezone
        sent_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return contract.parse_event({"id": event_id, "type": kind, "ts": sent_at, "message": {
        "message_id": message_id or f"g{event_id}", "conversation": conversation, "sender": sender,
        "identity": identity, "sent_at": sent_at, "in_reply_to": in_reply_to, "text": text, "from_me": False,
        "is_reaction": False, "edited": kind == "message.edited", "has_attachments": False}})


def rows(status: Optional[str] = None) -> List[dict]:
    found = [r for r in message_store.list_messages(limit=500) if r["direction"] == "in"]
    return sorted([r for r in found if status is None or r["status"] == status], key=lambda r: r["received_at"])
