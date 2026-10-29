
from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest

from src.core.db import connect, db_path_for
from src.core.swarm import delivery, store, watch
from src.core.unread_store import UnreadStore
from tests.python.swarm.test_swarm_agent_real_tmux import _until, world  # noqa: F401

API = "/swarm"


def _make(client, world, job: str):
    async def go() -> int:
        made = await client.post(f"{API}/agents", json={"repo_dir": str(world.repo), "job": job, "rank": "feature",
                                                        "effort": "high", "effort_reason": "wide change"})
        assert made.status_code == 201, made.text
        return made.json()["id"]
    return go()


def _kickoffs(world, agent_id: int) -> int:
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        return conn.execute("SELECT COUNT(*) FROM swarm_deliveries WHERE agent_id = ? AND source = 'wake_prompt'", (agent_id,)).fetchone()[0]


def _reading(name: str):
    observation = SimpleNamespace(verdict=SimpleNamespace(reason="idle"), evidence=SimpleNamespace(dialog=None))
    return SimpleNamespace(key=UnreadStore.compose_key(name, watch._epochs.get(name))), observation


@pytest.mark.asyncio
async def test_a_gate_cleared_outside_the_card_closes_it_and_a_lost_kickoff_lands_once(world, monkeypatch):  # noqa: F811
    closed = []

    async def close_open_cards(thread_key, prefix):
        closed.append((thread_key, prefix))

    monkeypatch.setattr(world.port, "close_open_cards", close_open_cards)
    monkeypatch.setattr(delivery, "KICKOFF_GRACE_S", 0.0)

    async def past_gate(*_args):
        return True

    monkeypatch.setattr(delivery, "_past_trust_gate", past_gate)
    watch.reset()
    transport = httpx.ASGITransport(app=world.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t/api/v1") as client:
        agent_id = await _make(client, world, "swap models")
        world.busy["on"] = True
        sent = await client.post(f"{API}/agents/{agent_id}/messages", json={"text": "go"})
        assert sent.status_code == 200, sent.text
        detail = (await client.get(f"{API}/agents/{agent_id}")).json()
        with closing(connect(db_path_for(world.state), create=False)) as conn:
            wake_id = store.get_open_wake(conn, agent_id)["id"]
        delivery._trust_posted.add((wake_id, "fp1"))
        delivery._trust_card_at[(wake_id, "fp1")] = delivery.datetime.now(delivery.timezone.utc)
        world.busy["on"] = False
        target, observation = _reading(detail["tmux_session"])
        watch.on_observation(target, observation)
        await _until(lambda: (detail["thread_key"], delivery.TRUST_PREFIX) in closed, "the trust card to close")
        await _until(lambda: _kickoffs(world, agent_id) == 1 and any("desk" in t for t in world.pasted), "the held kickoff to land")
        await asyncio.sleep(0.5)
        assert _kickoffs(world, agent_id) == 1 and sum("desk" in t for t in world.pasted) == 1

        before = len(world.pasted)
        with monkeypatch.context() as lost:
            lost.setattr(delivery, "send_wake_prompt", lambda *a, **k: None)
            second = await _make(client, world, "tidy the docs")
            woke = await client.post(f"{API}/agents/{second}/messages", json={"text": "hello"})
            assert woke.status_code == 200, woke.text
        await asyncio.sleep(0.5)
        assert _kickoffs(world, second) == 0
        watch.reset()
        assert await watch.boot(world.app.state) == 2
        await _until(lambda: _kickoffs(world, second) == 1, "the boot pass to deliver the kickoff")
        await asyncio.sleep(0.5)
        assert await watch.boot(world.app.state) == 2
        await asyncio.sleep(0.5)
        assert _kickoffs(world, second) == 1 and _kickoffs(world, agent_id) == 1
        assert sum("desk" in t for t in world.pasted[before:]) == 1
    watch.reset()
