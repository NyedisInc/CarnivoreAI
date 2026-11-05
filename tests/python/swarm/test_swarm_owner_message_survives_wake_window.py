
from __future__ import annotations

import asyncio
from contextlib import closing

import httpx
import pytest

from src.core.db import connect, db_path_for
from src.core.swarm import delivery
from tests.python.swarm.test_swarm_agent_real_tmux import _until, world  # noqa: F401

API = "/swarm"
WORDS = "swap the models please"


def _owner_rows(world, agent_id: int) -> int:
    with closing(connect(db_path_for(world.state), create=False)) as conn:
        return conn.execute("SELECT COUNT(*) FROM swarm_deliveries WHERE agent_id = ? AND source = 'owner_chat'", (agent_id,)).fetchone()[0]


@pytest.mark.asyncio
async def test_owner_words_land_once_after_the_wake_prompt_window_expires(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(delivery, "WAKE_PROMPT_S", 0.3)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=world.app), base_url="http://t/api/v1") as client:
        made = await client.post(f"{API}/agents", json={"repo_dir": str(world.repo), "job": "swap models", "rank": "feature",
                                                        "effort": "high", "effort_reason": "wide change"})
        assert made.status_code == 201, made.text
        agent_id = made.json()["id"]
        world.busy["on"] = True
        sent = await client.post(f"{API}/agents/{agent_id}/messages", json={"text": WORDS})
        assert sent.status_code == 200 and sent.json()["outcome"] == "waking", sent.text
        await asyncio.sleep(0.8)
        assert not any(WORDS in t for t in world.pasted)
        world.busy["on"] = False
        await _until(lambda: any(WORDS in t for t in world.pasted), "the owner words to land")
        await asyncio.sleep(0.5)
        assert sum(WORDS in t for t in world.pasted) == 1 and _owner_rows(world, agent_id) == 1
        await delivery._replay_owner_words(world.app.state, agent_id)
        await asyncio.sleep(0.3)
        assert sum(WORDS in t for t in world.pasted) == 1
