
from __future__ import annotations

import asyncio
from contextlib import closing

from src.core.messaging import events, store

from .conftest import UUID_A, UUID_B, bind, received, rows, screen


def _drain(world, uuid=UUID_A):
    asyncio.run(world.rt.drainer.drain(uuid))


def _event(world, event):
    asyncio.run(events.handle_event(world.rt, world.rt.providers[world.pid], event))


def test_a_text_while_a_rig_permission_dialog_is_open_is_held_then_delivered_when_it_closes(world):
    bind(world, UUID_A, default=True)
    world.screens["cloude_trader"] = screen("claude_permission")
    _event(world, received(1, "restart the trader feed"))
    _drain(world)
    assert world.pasted == []
    held = rows("held")
    assert [r["reason"] for r in held] == ["dialog_open"]
    held_notices = [s for s in world.provider.sent if s["text"].startswith("held for trader")]
    assert len(held_notices) == 1
    _drain(world)
    assert world.pasted == [] and len([s for s in world.provider.sent if s["text"].startswith("held for")]) == 1
    world.screens["cloude_trader"] = "> \n"
    _drain(world)
    assert len(world.pasted) == 1 and "restart the trader feed" in world.pasted[0]["text"]
    assert "held while a dialog was open" in world.pasted[0]["text"]
    assert rows("delivered") and not rows("held")
    _drain(world)
    assert len(world.pasted) == 1


def test_a_question_status_or_startup_gate_holds_without_a_capture(world):
    bind(world, UUID_A, default=True)
    world.manager.infos["ses_a"].activity_status = "question"
    _event(world, received(1, "yes"))
    _drain(world)
    world.manager.infos["ses_a"].activity_status = "idle"
    world.manager.infos["ses_a"].startup_gate = "awaiting_startup_prompt"
    _drain(world)
    assert world.pasted == [] and rows("held")[0]["reason"] == "dialog_open"


def test_an_unreadable_pane_is_held_fail_closed(world):
    bind(world, UUID_A, default=True)
    world.screens.pop("cloude_trader")
    _event(world, received(1, "status"))
    _drain(world)
    assert world.pasted == [] and rows("held")[0]["reason"] == "dialog_unreadable"


def test_three_pending_texts_arrive_as_one_batch_oldest_first_each_dated(world):
    bind(world, UUID_A, default=True)
    world.screens["cloude_trader"] = screen("claude_permission")
    _event(world, received(1, "first", sent_at="2026-10-09T18:00:00Z"))
    _event(world, received(2, "second", sent_at="2026-10-09T19:00:00Z"))
    _event(world, received(3, "third", sent_at="2026-10-09T20:00:00Z"))
    _drain(world)
    world.screens["cloude_trader"] = "> \n"
    _drain(world)
    assert len(world.pasted) == 1
    text = world.pasted[0]["text"]
    assert text.splitlines()[0].startswith("3 messages from joe (imessage, via carnivore), oldest first")
    lines = [ln for ln in text.splitlines() if ln.startswith("[")]
    assert [ln.rsplit("] ", 1)[1] for ln in lines] == ["first", "second", "third"]
    assert all("ago" in ln for ln in lines)
    assert text.splitlines()[-1] == "reply with messaging_send."
    assert len({r["batch_id"] for r in rows("delivered")}) == 1


def test_a_replayed_event_id_is_not_delivered_twice(world):
    bind(world, UUID_A, default=True)
    event = received(7, "only once")
    _event(world, event)
    _drain(world)
    world.rt.providers[world.pid].row["cursor"] = 0
    _event(world, event)
    _drain(world)
    assert len(world.pasted) == 1 and len(rows()) == 1


def _asleep_rig(world, monkeypatch, *, wake_status="started", ready=True):
    from types import SimpleNamespace

    from src.api import session_sleep_routes
    from src.core.messaging import delivery
    from src.core.session_delivery import bring_up

    bind(world, UUID_A, default=True)
    world.cards[UUID_A] = {**world.cards[UUID_A], "asleep": True, "status": "asleep"}
    calls, readied = [], []

    async def wake(app_state, uuid, agent_type=None):
        calls.append(uuid)
        return SimpleNamespace(status=wake_status, detail="", code="wrapper_needed" if wake_status == "refused" else None)

    async def await_ready(self, uuid):
        readied.append(uuid)
        if not ready:
            raise bring_up.BringUpFailed("the woken session did not reach its prompt within 90 seconds")
        world.cards[UUID_A] = {**world.cards[UUID_A], "asleep": False, "status": "idle"}
        return "ses_a"

    monkeypatch.setattr(session_sleep_routes, "wake_by_uuid", wake)
    monkeypatch.setattr(delivery.Drainer, "_await_ready", await_ready)
    return calls, readied


def test_a_text_for_an_asleep_session_wakes_it_and_is_delivered_once_at_the_prompt(world, monkeypatch):
    calls, readied = _asleep_rig(world, monkeypatch)
    _event(world, received(1, "wake up and check"))
    _drain(world)
    assert calls == [UUID_A] and readied == [UUID_A]
    assert len(world.pasted) == 1 and "wake up and check" in world.pasted[0]["text"]
    assert "held while asleep" in world.pasted[0]["text"]
    assert rows("delivered") and not rows("held")
    _drain(world)
    assert len(world.pasted) == 1 and calls == [UUID_A]


def test_a_refused_wake_keeps_the_text_held_and_delivers_nothing(world, monkeypatch):
    calls, readied = _asleep_rig(world, monkeypatch, wake_status="refused")
    _event(world, received(1, "wake up and check"))
    _drain(world)
    assert calls == [UUID_A] and readied == [] and world.pasted == []
    assert [r["reason"] for r in rows("held")] == ["asleep_wake_refused"]
    assert len([s for s in world.provider.sent if s["text"].startswith("could not wake")]) <= 1


def test_a_wake_that_raises_keeps_the_text_held(world, monkeypatch):
    from src.api import session_sleep_routes

    _asleep_rig(world, monkeypatch)

    async def boom(app_state, uuid, agent_type=None):
        raise RuntimeError("tmux gone")

    monkeypatch.setattr(session_sleep_routes, "wake_by_uuid", boom)
    _event(world, received(1, "hello"))
    _drain(world)
    assert world.pasted == [] and [r["reason"] for r in rows("held")] == ["asleep_wake_refused"]


def test_a_woken_session_that_is_slow_keeps_the_text_held_for_its_first_status_edge(world, monkeypatch):
    calls, readied = _asleep_rig(world, monkeypatch, ready=False)
    _event(world, received(1, "wake up and check"))
    _drain(world)
    assert calls == [UUID_A] and world.pasted == [] and [r["reason"] for r in rows("held")] == ["waking"]
    world.cards[UUID_A] = {**world.cards[UUID_A], "asleep": False, "status": "idle"}
    _drain(world)
    assert len(world.pasted) == 1 and calls == [UUID_A]


def test_a_deleted_session_loses_its_bindings_and_its_held_rows_fail(world):
    bind(world, UUID_B, default=True)
    _event(world, received(1, "hello"))
    world.cards.pop(UUID_B)
    with closing(store._conn()) as conn:
        conn.execute("DELETE FROM sessions WHERE session_uuid = ?", (UUID_B,))
    _drain(world, UUID_B)
    assert store.list_bindings(session_uuid=UUID_B) == []
    assert rows("failed")[0]["reason"] == "session_deleted"
