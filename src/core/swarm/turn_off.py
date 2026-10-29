
from __future__ import annotations

import asyncio
from typing import Any, Dict

import structlog

from src.core.swarm import body, store, teardown, thread_port
from src.core.swarm.body import BodyError

logger = structlog.get_logger()


class TurnOffRefused(BodyError):
    pass


async def close_cards(thread_key: str) -> None:
    port = thread_port.get()
    if port is None:
        return
    refs = {c["swarm_ref"] for c in await port.open_cards() if c.get("thread_key") == thread_key and c.get("swarm_ref")}
    for ref in sorted(refs):
        await port.close_open_cards(thread_key, ref)


async def run(app_state: Any, agent_id: int) -> Dict[str, Any]:
    agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
    if agent is None or agent["torn_down_at"] is not None:
        raise store.AgentNotFound(agent_id)
    if agent["rank"] == "alpha":
        raise TurnOffRefused("SysOp cannot be turned off")
    kids = await body.run_db(lambda c: store.list_agents(c, parent_id=agent_id))
    if kids:
        raise TurnOffRefused(f"{agent['display_name']} still has agents under it: {', '.join(k['display_name'] for k in kids)}; turn those off first")
    commit = None
    if agent["state"] in ("awake", "waking") and await body.detect_death(app_state, agent):
        agent = await body.run_db(lambda c: store.get_agent(c, agent_id)) or agent
    if agent["state"] == "awake":
        commit = (await body.sleep(app_state, agent_id, "teardown")).commit
    elif agent["state"] != "asleep":
        raise TurnOffRefused(f"{agent['display_name']} is {agent['state']}; try again in a moment")
    await close_cards(agent["thread_key"])
    current = await body.run_db(lambda c: store.get_agent(c, agent_id)) or agent
    await asyncio.to_thread(teardown.archive_and_tombstone, current)
    logger.info("swarm_agent_turned_off", agent_id=agent_id, rank=agent["rank"], slug=agent["slug"])
    return {"state": "torn_down", "commit": commit}
