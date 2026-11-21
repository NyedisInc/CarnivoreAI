
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any, Dict, Optional

import structlog

from src.plugins.reviewboard.public.capability import REVISION_HEADER, visitor_key
from src.plugins.reviewboard.public.headers import header_values
from src.plugins.reviewboard.public.presence import BEAT_S
from src.plugins.reviewboard.public.read import READER
from src.plugins.reviewboard.public.respond import send_json, send_state
from src.plugins.reviewboard.public.deps import LinkRow, RevisionRead
from src.plugins.reviewboard.public.resolve import Refusal
from src.plugins.reviewboard.public.singleflight import SingleFlight

logger = structlog.get_logger()

HOLD_S = 6.0
MAX_HELD_PER_LINK = 25
MAX_HELD = 32
BUSY_RETRY_S = 30


class Waiters:

    def __init__(self) -> None:
        self.per_link: Counter[str] = Counter()

    def admit(self, link_id: str) -> bool:
        if self.per_link[link_id] >= MAX_HELD_PER_LINK or sum(self.per_link.values()) >= MAX_HELD:
            return False
        self.per_link[link_id] += 1
        return True

    def leave(self, link_id: str) -> None:
        self.per_link[link_id] -= 1
        if self.per_link[link_id] <= 0:
            del self.per_link[link_id]


WAITERS = Waiters()
_NEWEST: SingleFlight[Optional[str]] = SingleFlight()
_RECHECKS: SingleFlight[RevisionRead] = SingleFlight()


def _shown(scope: Any) -> str:
    values = header_values(scope, REVISION_HEADER)
    return values[0].decode("ascii", errors="replace") if len(values) == 1 else ""


async def _hold(link: LinkRow, shown: str) -> Dict[str, Any]:
    resolver = READER.resolver
    if resolver is None:
        raise Refusal("unavailable")
    event = asyncio.Event()
    stop_following = resolver.deps.follow(event.set)
    deadline = asyncio.get_running_loop().time() + HOLD_S
    try:
        while True:
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                return {"state": "same"}
            try:
                await asyncio.wait_for(event.wait(), left)
            except asyncio.TimeoutError:
                return {"state": "same"}
            event.clear()
            newest = await _NEWEST.run(link.board, lambda: resolver.call(resolver.deps.latest, link.board))
            if newest == shown:
                continue
            rev = await _RECHECKS.run(link.id, lambda: resolver.recheck(link.id))
            if rev.revision != shown:
                return {"state": "newer", "revision": rev.revision}
    finally:
        stop_following()


async def wait_next(scope: Any, receive: Any, send: Any) -> None:
    resolver = READER.resolver
    if resolver is None:
        await send_state(send, "unavailable")
        return
    try:
        link, rev = await resolver.open(scope, budget="background")
        shown = _shown(scope)
        key = visitor_key(scope)
        if key:
            resolver.deps.beat(link.id, link.board, key)
        if rev.revision != shown:
            answer: Dict[str, Any] = {"state": "newer", "revision": rev.revision}
        elif link.mode != "follow":
            answer = {"state": "fixed", "retry": BEAT_S}
        elif not WAITERS.admit(link.id):
            answer = {"state": "same", "retry": BUSY_RETRY_S}
        else:
            try:
                answer = await _hold(link, shown)
            finally:
                WAITERS.leave(link.id)
    except Refusal as refused:
        await send_state(send, refused.state)
        return
    await send_json(send, 200, answer, {"Connection": "close"})
