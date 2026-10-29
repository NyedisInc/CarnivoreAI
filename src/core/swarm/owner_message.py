
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from src.core.swarm import body, delivery, learning, push, store, thread_port

logger = structlog.get_logger()

REMEMBER_LINE = "To keep these words as a fact, call swarm_remember with owner_message_ref={ref} and no text."
DELIVERED, HELD, WAKING = "delivered", "held", "waking"


class SwarmOff(body.BodyError):
    pass


@dataclass(frozen=True)
class OwnerMessageResult:

    message_ref: str
    outcome: str


async def post_owner_message(app_state: object, agent_id: int, text: str) -> OwnerMessageResult:
    port = thread_port.get()
    if port is None:
        raise SwarmOff("the huddle plugin is off")
    agent = await body.run_db(lambda c: store.get_agent(c, agent_id))
    if agent is None or agent["torn_down_at"] is not None:
        raise body.BodyError("no such agent")
    ref = await port.post_owner_message(agent["thread_key"], text)
    await body.run_db(lambda c: learning.queue_skip_level(c, agent, ref, text))
    await asyncio.to_thread(push.notify_thread, agent["thread_key"])
    remember = REMEMBER_LINE.format(ref=ref)
    if agent["state"] == "asleep":
        woke = await body.wake(app_state, agent_id, "owner_message", "owner", orders=f"{text}\n\n{remember}", owner_message_ref=ref)
        if woke.started:
            return OwnerMessageResult(ref, WAKING)
    outcome = await delivery.deliver_text(app_state, agent_id, f"{text}\n\n{remember}", source="owner_chat", authority="owner",
                                          owner_message_ref=ref)
    if outcome.startswith("refused:"):
        raise body.BodyError(f"{agent['display_name']} could not take the message ({outcome.split(':', 1)[1]})")
    return OwnerMessageResult(ref, outcome)
