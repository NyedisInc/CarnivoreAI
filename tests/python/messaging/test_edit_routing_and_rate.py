
from __future__ import annotations

import asyncio
import time

from src.core.messaging import events, message_store

from .conftest import UUID_A, UUID_B, bind, received, rows, screen


def _event(world, event):
    asyncio.run(events.handle_event(world.rt, world.rt.providers[world.pid], event))


def _drain(world, uuid=UUID_A):
    asyncio.run(world.rt.drainer.drain(uuid))


def test_an_edit_keeps_the_handle_stripped_like_the_original(world):
    bind(world, UUID_A)
    bind(world, UUID_B)
    world.screens["cloude_trader"] = screen("claude_permission")
    world.screens["cloude_infra"] = screen("claude_permission")
    _event(world, received(1, "@infra check disk", message_id="gA"))
    _event(world, received(2, "@infra check memory", message_id="gA", kind="message.edited"))
    held = [r for r in rows() if r["status"] == "queued"]
    assert [r["text"] for r in held] == ["check memory"]


def test_an_edit_that_retargets_drops_the_stale_original(world):
    bind(world, UUID_A)
    bind(world, UUID_B)
    world.screens["cloude_trader"] = screen("claude_permission")
    world.screens["cloude_infra"] = screen("claude_permission")
    _event(world, received(1, "@infra check disk", message_id="gA"))
    _event(world, received(2, "@trader check disk", message_id="gA", kind="message.edited"))
    assert [r["reason"] for r in rows("failed")] == ["unsent"]
    assert not [r for r in rows() if r["status"] == "queued"]


def test_an_at_all_text_counts_once_against_the_inbound_limit(world):
    bind(world, UUID_A)
    bind(world, UUID_B)
    world.screens["cloude_trader"] = screen("claude_permission")
    world.screens["cloude_infra"] = screen("claude_permission")
    _event(world, received(1, "@all status", message_id="gA"))
    since = time.time() - 3600
    assert len(rows()) == 2
    assert message_store.count_since(since=since, direction="in", accepted_only=True) == 2
    assert message_store.count_since(since=since, direction="in", accepted_only=True, distinct_messages=True) == 1
