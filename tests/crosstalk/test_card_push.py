
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from src.core.crosstalk import card_push, store
from src.core.db_steps import STEPS

PENDING = "native_receipt_pending:" + "a" * 32


@pytest.fixture
def wired(tmp_path, monkeypatch):
    def connect():
        connection = sqlite3.connect(tmp_path / "cloude.db", isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    with connect() as connection:
        STEPS[56](connection)
        STEPS[89](connection)
        STEPS[93](connection)
        for mid, status, reason in (("m-del", "delivering", None), ("m-held", "held", PENDING)):
            connection.execute("""INSERT INTO crosstalk_messages
                (id,thread,sender_key,receiver_key,sender_id,receiver_id,receiver_epoch,sender_name,sender_provider,
                 text,status,reason,created_at,expires_at)
                VALUES (?,'t1','alpha','agent','ses_a','ses_b',7,'Alpha','claude','ping','%s',?,1,9999999999)""" % status,
                               (mid, reason))
    monkeypatch.setattr(store, "_conn", connect)
    monkeypatch.setattr(store, "_notify", lambda: None)
    monkeypatch.setattr(store, "_notify_swarm", lambda *keys: None)
    loop = asyncio.new_event_loop()
    frames: list = []
    state = {"on": True}
    card_push.install(lambda frame: frames.append(frame) or 1, loop, lambda: {"values": {"crosstalk_cards": state["on"]}})

    def drain() -> list:
        loop.run_until_complete(asyncio.sleep(0))
        return frames

    yield store, state, drain
    card_push.uninstall()
    loop.close()


def test_finish_delivered_sends_exactly_one_frame_with_the_card_fields(wired):
    bus, _state, drain = wired
    bus.finish("m-del", "delivered")
    bus.finish("m-del", "delivered")
    frames = drain()
    assert len(frames) == 1
    frame = frames[0]
    assert frame["type"] == "crosstalk.card" and frame["id"] == "m-del" and frame["thread"] == "t1"
    assert (frame["sender_id"], frame["receiver_id"], frame["preview"]) == ("ses_a", "ses_b", "ping")
    assert frame["at"]


def test_nothing_is_sent_while_the_plugin_is_off_or_for_a_non_delivery(wired):
    bus, state, drain = wired
    state["on"] = False
    bus.finish("m-del", "delivered")
    assert drain() == []
    state["on"] = True
    bus.finish("m-held", "failed")
    assert drain() == []


def test_a_held_native_message_settled_by_its_receivers_read_sends_one_frame(wired):
    bus, _state, drain = wired
    bus.messages_for("agent")
    bus.messages_for("agent")
    frames = drain()
    assert [f["id"] for f in frames] == ["m-held"]


def test_a_mirrored_native_message_sends_one_frame_and_a_replay_none(wired):
    bus, _state, drain = wired
    kwargs = dict(native_key="nk-1", sender_id="ses_a", receiver_id="ses_b", sender_uuid=None, receiver_uuid=None,
                  sender_name="Alpha", text="hello native")
    bus.mirror_native(**kwargs)
    bus.mirror_native(**kwargs)
    frames = drain()
    assert len(frames) == 1 and frames[0]["preview"] == "hello native"


def test_the_preview_is_short_and_a_system_notice_draws_no_card(wired):
    _bus, _state, drain = wired
    long = card_push.frame_of({"id": "m", "text": "x" * 500})["preview"]
    assert len(long) == card_push.PREVIEW_CHARS and long.endswith("…")
    card_push.announce({"id": "s", "source": "system", "text": "idle"})
    assert drain() == []


def test_with_nothing_installed_announce_is_a_no_op():
    card_push.uninstall()
    card_push.announce({"id": "m", "text": "x"})


def test_a_new_install_ships_off_and_the_gate_follows_the_stored_preference():
    card_push.install(lambda frame: 1, asyncio.new_event_loop(), lambda: {"values": {}})
    assert card_push.enabled() is False
    block = {"values": {"crosstalk_cards": True}}
    card_push.install(lambda frame: 1, asyncio.new_event_loop(), lambda: block)
    assert card_push.enabled() is True
    block["values"]["crosstalk_cards"] = False
    assert card_push.enabled() is False
    card_push.uninstall()
    assert card_push.enabled() is False
