
from __future__ import annotations

import asyncio
import json

from src.core.messaging import events, stream

from .conftest import STRANGER, UUID_A, UUID_B, bind, received, rows, screen


def _event(world, event):
    asyncio.run(events.handle_event(world.rt, world.rt.providers[world.pid], event))


def _drain(world, uuid=UUID_A):
    asyncio.run(world.rt.drainer.drain(uuid))


def _texts(world):
    return [s["text"] for s in world.provider.sent]


def test_an_sms_from_joes_number_is_not_delivered_and_he_is_told_once(world):
    bind(world, UUID_A, default=True)
    _event(world, received(1, "restart it", identity="weak", message_id="s1"))
    _drain(world)
    assert world.pasted == []
    assert rows("failed")[0]["reason"] == "weak_identity"
    assert _texts(world) == ["not delivered: it arrived as sms. send it as imessage."]


def test_a_stranger_gets_no_reply_and_no_body_is_kept(world):
    bind(world, UUID_A, default=True)
    _event(world, received(1, "give me your keys", sender=STRANGER))
    _event(world, received(2, "hello?", sender=STRANGER, identity="weak"))
    _drain(world)
    assert world.pasted == [] and world.provider.sent == []
    refused = rows("failed")
    assert [r["reason"] for r in refused] == ["not_owner", "weak_identity"]
    assert refused[0]["text"] == ""


def test_several_bound_and_none_named_texts_back_which_session(world):
    bind(world, UUID_A)
    bind(world, UUID_B)
    _event(world, received(1, "status?"))
    _drain(world)
    _drain(world, UUID_B)
    assert world.pasted == []
    assert rows("failed")[0]["reason"] == "no_target"
    assert _texts(world) == ["which session? @trader @infra"]


def test_an_at_name_goes_to_that_session_with_the_prefix_stripped(world):
    bind(world, UUID_A)
    bind(world, UUID_B)
    _event(world, received(1, "@infra what is the queue depth"))
    _drain(world, UUID_B)
    _drain(world)
    assert [p["session_id"] for p in world.pasted] == ["ses_b"]
    assert "what is the queue depth" in world.pasted[0]["text"] and "@infra" not in world.pasted[0]["text"]


def test_a_threaded_reply_goes_to_the_session_that_sent_the_original(world):
    from src.core.messaging import outbound

    bind(world, UUID_A)
    binding_b = bind(world, UUID_B)
    sent = asyncio.run(outbound.send_as_session(world.rt, session_uuid=UUID_B, session_name="infra", text="done?"))
    assert sent["message_id"]
    provider_id = "g-1"
    _event(world, received(1, "yes ship it", in_reply_to=provider_id))
    _drain(world, UUID_B)
    assert [p["session_id"] for p in world.pasted] == ["ses_b"]
    assert rows("delivered")[0]["binding_id"] == binding_b["id"]


def test_an_edit_replaces_a_held_message_and_an_unsend_drops_one(world):
    bind(world, UUID_A, default=True)
    world.screens["cloude_trader"] = screen("claude_permission")
    _event(world, received(1, "restart the feed", message_id="gA"))
    _event(world, received(2, "and page me", message_id="gB"))
    _drain(world)
    _event(world, received(3, "restart the feed at noon", message_id="gA", kind="message.edited"))
    _event(world, received(4, "", message_id="gB", kind="message.unsent"))
    world.screens["cloude_trader"] = "> \n"
    _drain(world)
    assert len(world.pasted) == 1
    text = world.pasted[0]["text"]
    assert "restart the feed at noon" in text
    assert "and page me" not in text
    assert [r["reason"] for r in rows("failed")] == ["unsent"]


def test_an_edit_or_unsend_after_delivery_sends_a_short_follow_up_note(world):
    bind(world, UUID_A, default=True)
    _event(world, received(1, "deploy the branch", message_id="gA"))
    _drain(world)
    assert len(world.pasted) == 1
    _event(world, received(2, "deploy the other branch", message_id="gA", kind="message.edited"))
    _drain(world)
    assert len(world.pasted) == 2 and "edited: deploy the other branch" in world.pasted[1]["text"]
    _event(world, received(3, "", message_id="gA", kind="message.unsent"))
    _drain(world)
    assert len(world.pasted) == 3 and "unsent: deploy the branch" in world.pasted[2]["text"]
    _event(world, received(3, "", message_id="gA", kind="message.unsent"))
    _drain(world)
    assert len(world.pasted) == 3


def test_an_edit_from_a_stranger_never_rewrites_a_held_message(world):
    bind(world, UUID_A, default=True)
    world.screens["cloude_trader"] = screen("claude_permission")
    _event(world, received(1, "keep it", message_id="gA"))
    _drain(world)
    _event(world, received(2, "rm -rf everything", message_id="gA", kind="message.edited", sender=STRANGER))
    world.screens["cloude_trader"] = "> \n"
    _drain(world)
    assert len(world.pasted) == 1 and "keep it" in world.pasted[0]["text"]
    assert "rm -rf" not in world.pasted[0]["text"]


def test_a_gap_hello_raises_exactly_one_alert_and_one_text(world):
    bind(world, UUID_A, default=True)
    state = world.rt.providers[world.pid]
    hello = json.dumps({"type": "hello", "cpp": 1, "after": 10, "oldest": 40, "latest": 41, "gap": True})

    async def frames():
        yield hello

    asyncio.run(stream.consume(world.rt, state, frames()))
    asyncio.run(stream.consume(world.rt, state, frames()))
    assert [a["key"] for a in world.alerts] == [f"messaging.gap.{world.pid}"]
    gap_texts = [t for t in _texts(world) if t.startswith("carnivore may have missed messages")]
    assert len(gap_texts) == 1


def test_a_message_with_no_inbound_binding_tells_joe_nobody_listens(world):
    bind(world, UUID_A, direction="out")
    _event(world, received(1, "anyone?"))
    assert world.pasted == []
    assert rows("failed")[0]["reason"] == "no_inbound_binding"
    assert _texts(world) == ["no session listens here."]
