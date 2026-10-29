
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import rules, service
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.swarm import AgentRef, SwarmError

logger = structlog.get_logger()

AGENT_WAKING = "agent_waking"
WAKING_CODES = frozenset({"pane_not_an_agent", "session_gone", "session_not_found"})
SOURCE = "huddle_tell"


def as_waking(ctx: CplugContext, key: str, exc: HTTPException) -> HTTPException:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    swarm = service.swarm_of(ctx)
    if swarm is None or not rules.agent_id_of(key) or detail.get("code") not in WAKING_CODES or not swarm.is_waking(key):
        return exc
    return HTTPException(status_code=409, detail={"code": AGENT_WAKING, "detail": "the agent is starting; the tell waits"})


async def wake_if_asleep(ctx: CplugContext, key: str) -> bool:
    swarm = service.swarm_of(ctx)
    if swarm is None or not rules.agent_id_of(key):
        return False
    agent = await swarm.agent_for_list(key)
    if agent is None or agent.session_id is not None:
        return False
    try:
        await swarm.wake(agent.id, "owner_message")
    except SwarmError as exc:
        raise HTTPException(status_code=409, detail={"code": "agent_wake_refused", "detail": str(exc)}) from exc
    return True


async def target_agent(ctx: CplugContext, target: str) -> Optional[AgentRef]:
    swarm = service.swarm_of(ctx)
    thread = await swarm.thread_for_session(target) if swarm is not None else None
    return await swarm.agent_for_list(thread) if thread else None


def classify(changes: List[dict], cursors: List[int]) -> Tuple[str, Optional[str]]:
    owner_ref: Optional[Tuple[int, str]] = None
    for change, since in zip(changes, cursors):
        if any(i["created_seq"] > since and i["created_key"] != rules.OWNER_KEY for i in change["items"]):
            return "data", None
        for m in change["messages"]:
            if m["author_key"] != rules.OWNER_KEY:
                return "data", None
            if owner_ref is None or m["id"] > owner_ref[0]:
                owner_ref = (m["id"], f"huddle:msg:{m['id']}")
    return ("owner", owner_ref[1]) if owner_ref else ("data", None)


async def record_before_paste(ctx: CplugContext, run: Any, target: str, key: str,
                              told: List[Tuple[str, int]], has_lead: bool = False) -> Optional[int]:
    agent = await target_agent(ctx, target)
    if agent is None:
        return None
    changes = [await run(lambda k=k, c=c: service.store(ctx).changes(c, k, all_live_groups=False)) for k, c in told]
    authority, ref = classify(changes, [c for _, c in told])
    if has_lead:
        authority, ref = "data", None
    owner_text = "\n\n".join(m["text"] for ch in changes for m in ch["messages"] if m["author_key"] == rules.OWNER_KEY) if ref else None
    return await run(lambda: ctx.swarm.record_delivery(agent.id, authority, SOURCE, ref or f"huddle:list:{key}", owner_text))


async def discard(ctx: CplugContext, run: Any, delivery_id: Optional[int], refusal: HTTPException) -> None:
    if delivery_id is not None:
        await run(lambda: ctx.swarm.discard_delivery(delivery_id, refusal))
