
from __future__ import annotations

import asyncio

from src.core.swarm import settings as swarm_settings, stream
from src.cplugs.huddle.swarm_port import TaskManagerSwarmPort
from tests.python.cplugs.huddle.test_task_manager_agent_lists import BASE, world  # noqa: F401


def _page(world, monkeypatch, on: bool) -> list:
    monkeypatch.setattr(swarm_settings, "read_current", lambda: swarm_settings.SwarmConfig(chat_card_bodies=on))
    monkeypatch.setattr(stream, "EXTRA_SOURCES", [])
    agent = {"id": int(world.key.split(":")[1]), "thread_key": world.key}
    return asyncio.run(stream.page(agent))["entries"]


def test_a_board_card_stays_out_of_the_chat_unless_the_setting_is_on(world, monkeypatch):
    ctx = world.host.context("huddle")
    port = TaskManagerSwarmPort(ctx)
    ctx.swarm.register_thread_port(port)
    card = world.client.post(f"{BASE}/lists/{world.key}/items", json={"text": "a long card body nobody should pay tokens for"}).json()["id"]
    asyncio.run(port.post_owner_message(world.key, "go"))
    asyncio.run(port.post_card(world.key, "question", "ship it?", "ready to ship", "card:1"))
    notice = asyncio.run(port.post_card(world.key, "info", "wake failed", "Ui-Fixes could not start", "wake_failed:1:1"))

    assert swarm_settings.SwarmConfig().chat_card_bodies is False
    off = _page(world, monkeypatch, on=False)
    assert has_item(off, card) is False
    assert has_item(off, notice) is False
    assert {e["kind"] for e in off} >= {"owner", "card"}

    on = _page(world, monkeypatch, on=True)
    assert has_item(on, card) is True
    assert has_item(on, notice) is True


def has_item(entries: list, item_id: int) -> bool:
    return f"item:{item_id}" in {e["id"] for e in entries}
