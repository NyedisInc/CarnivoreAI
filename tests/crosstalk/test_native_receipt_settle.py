
from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.core.crosstalk import store
from src.core.crosstalk.delivery import claude_native
from src.core.db_steps import STEPS
from src.models import Session, SessionInfo

CONVERSATION = "11111111-1111-4111-8111-111111111111"
NATIVE_ID = "a" * 32
PENDING = f"native_receipt_pending:{NATIVE_ID}:{CONVERSATION}"


@pytest.fixture
def bus(tmp_path, monkeypatch):
    def connect():
        connection = sqlite3.connect(tmp_path / "cloude.db", isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    with connect() as connection:
        STEPS[56](connection)
        STEPS[89](connection)
        STEPS[93](connection)
        connection.execute("""INSERT INTO crosstalk_messages
            (id,thread,sender_key,receiver_key,sender_id,receiver_id,receiver_epoch,sender_name,sender_provider,
             text,status,reason,created_at,expires_at)
            VALUES ('m1','t1','alpha','agent','ses_a','ses_b',7,'Alpha','claude','ping','held',?,1,9999999999)""",
                           (PENDING,))
    monkeypatch.setattr(store, "_conn", connect)
    monkeypatch.setattr(store, "_notify", lambda: None)
    monkeypatch.setattr(store, "_notify_swarm", lambda *keys: None)
    return store


def test_receiver_reading_a_held_native_message_settles_it(bus):
    assert bus.messages_for("alpha")[0]["status"] == "held"
    assert bus.get("m1")["status"] == "held"
    rows = bus.messages_for("agent")
    assert rows[0]["status"] == "delivered" and rows[0]["reason"] is None
    stored = bus.get("m1")
    assert stored["status"] == "delivered" and stored["delivered_at"] and stored["reason"] is None
    assert bus.claim_for("agent") is None


def _info(tmp_path, *, epoch=7):
    return SessionInfo(session=Session(id="ses_b", working_dir=str(tmp_path), tmux_created_epoch=epoch),
                       tmux_session="cloude_x", claude_session_uuid=None)


def _registry(monkeypatch, **fields):
    monkeypatch.setattr(claude_native, "registry_for_session", lambda **kwargs: SimpleNamespace(**fields))


def _transcript(tmp_path, monkeypatch, rows):
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(claude_native, "conversation_presence", lambda *a, **k: SimpleNamespace(path=path))


def test_lost_frame_leaves_held_but_unreadable_registry_does_not(tmp_path, monkeypatch):
    _transcript(tmp_path, monkeypatch, [])
    message = {"id": "m1", "reason": PENDING, "receiver_id": "ses_b", "receiver_epoch": 7, "sender_name": "Alpha"}
    info = _info(tmp_path)
    _registry(monkeypatch, verdict="unreadable", known=False, session_uuid=None)
    assert asyncio.run(claude_native.deliver(None, info, message)) == ("held", PENDING)
    _registry(monkeypatch, verdict="ok", known=True, session_uuid=CONVERSATION)
    assert asyncio.run(claude_native.deliver(None, info, message)) == ("held", PENDING)
    for fields in ({"verdict": "absent", "known": False, "session_uuid": None},
                   {"verdict": "ok", "known": True, "session_uuid": "22222222-2222-4222-8222-222222222222"}):
        _registry(monkeypatch, **fields)
        status, reason = asyncio.run(claude_native.deliver(None, info, message))
        assert status == "failed" and reason.startswith("native_frame_lost")


def test_pending_receipt_carried_across_a_wake_still_confirms(tmp_path, monkeypatch):
    message = {"id": "m1", "reason": PENDING, "receiver_id": "ses_old", "receiver_epoch": 1, "sender_name": "Alpha"}
    info = _info(tmp_path, epoch=9)
    _transcript(tmp_path, monkeypatch, [{"origin": {"kind": "peer", "msg_id": NATIVE_ID}}])
    assert asyncio.run(claude_native.settle_after_wake(info, message)) == "delivered"
    _transcript(tmp_path, monkeypatch, [])
    assert asyncio.run(claude_native.settle_after_wake(info, message)) == ("failed", "receiver is a different pane instance")


def _set(bus, sql, *params):
    with bus._conn() as conn:
        conn.execute(sql, params)


@pytest.fixture
def announced(monkeypatch):
    seen = []
    monkeypatch.setattr(store.card_push, "announce", lambda row: seen.append(row["id"]))
    return seen


def _reply(bus, replier_key, replier_epoch, to_key, to_epoch, parent="m1", sender_id="ses_b"):
    bus.grant_contact(replier_key, to_key, replier_epoch, to_epoch)
    return bus.reserve(sender={"key": replier_key, "id": sender_id, "epoch": replier_epoch, "name": "B", "provider": "claude"},
                       receiver={"key": to_key, "id": "ses_a", "epoch": to_epoch, "name": "Alpha", "provider": "claude"},
                       text="done", in_reply_to=parent)


def test_receiver_reply_settles_a_held_native_message_and_expire_leaves_it(bus):
    _reply(bus, "agent", 7, "alpha", None)
    stored = bus.get("m1")
    assert stored["status"] == "delivered" and stored["delivered_at"] and stored["reason"] is None
    _set(bus, "UPDATE crosstalk_messages SET status='held', reason=?, delivered_at=NULL WHERE id='m1'", PENDING)
    _set(bus, "UPDATE crosstalk_messages SET expires_at=1 WHERE id='m1'")
    assert bus.expire() == []
    assert bus.get("m1")["status"] == "delivered"
    assert not [r for r in bus.messages_for("alpha") if r["source"] == "system"]


def test_expire_backstop_spares_a_held_message_with_a_receiver_reply(bus, monkeypatch):
    _reply(bus, "agent", 7, "alpha", None)
    with bus._conn() as conn:
        conn.execute("UPDATE crosstalk_messages SET status='held', reason=?, delivered_at=NULL, expires_at=1 WHERE id='m1'", (PENDING,))
    assert bus.expire() == []
    stored = bus.get("m1")
    assert stored["status"] == "delivered" and stored["delivered_at"]
    assert not [r for r in bus.messages_for("alpha") if r["source"] == "system"]


def test_reply_from_someone_else_does_not_settle(bus):
    _reply(bus, "alpha", None, "agent", 7, sender_id="ses_a")
    assert bus.get("m1")["status"] == "held"
    with bus._conn() as conn:
        conn.execute("UPDATE crosstalk_messages SET expires_at=1 WHERE id='m1'")
    bus.expire()
    assert bus.get("m1")["status"] == "expired"


def test_reply_time_settle_announces(bus, announced):
    _reply(bus, "agent", 7, "alpha", None)
    assert announced == ["m1"]


def test_backstop_settle_announces(bus, announced):
    _reply(bus, "agent", 7, "alpha", None)
    _set(bus, "UPDATE crosstalk_messages SET status='held', reason=?, delivered_at=NULL, expires_at=1 WHERE id='m1'", PENDING)
    announced.clear()
    bus.expire()
    assert announced == ["m1"]


@pytest.mark.parametrize("status,reason", [("held", "receiver has an open dialog or startup gate"), ("queued", None)])
def test_answered_row_that_is_not_native_pending_still_expires(bus, status, reason):
    _reply(bus, "agent", 7, "alpha", None)
    _set(bus, "UPDATE crosstalk_messages SET status=?, reason=?, delivered_at=NULL, expires_at=1 WHERE id='m1'", status, reason)
    bus.expire()
    assert bus.get("m1")["status"] == "expired"
    assert bus.next_expiry() != 1


def test_held_swarm_row_past_expiry_does_not_arm_the_expiry_timer(bus):
    _set(bus, "UPDATE crosstalk_messages SET source='swarm', status='held', reason='receiver has an open dialog or startup gate', expires_at=1 WHERE id='m1'")
    assert bus.expire() == []
    assert bus.get("m1")["status"] == "held"
    assert bus.next_expiry() is None
