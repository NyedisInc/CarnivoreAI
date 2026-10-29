
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

SETTLE_SECONDS = 4.0
POLL_SECONDS = 1.0
FIND_SECONDS = 15.0
RESTING = ("idle", "finished_unread")


class TurnNotEnded(Exception):

    def __init__(self, state: Optional[str], hint: Optional[str] = None, background: Optional[int] = None) -> None:
        super().__init__(state or "not listed")
        self.state, self.hint, self.background = state, hint, background


def blocker_text(info: Any, name: str) -> str:
    if info is None:
        return f"{name} is not listed right now; wait a moment, then send again"
    if at_turn_end(info):
        return ""
    state = info.activity_status
    if state in RESTING and info.activity_hint is not None:
        count = getattr(info, "background_open", None)
        if isinstance(count, int) and count > 0:
            return f"{name} still has {count} background {'shell' if count == 1 else 'shells'} running; stop {'it' if count == 1 else 'them'}, then send again"
        return f"{name} still has a background task running; wait for it to finish or stop it, then send again"
    if state in RESTING:
        return f"{name} is still starting up or waiting on a dialog; answer it, then send again"
    if state == "question":
        return f"{name} is waiting for your answer; answer it, then send again"
    return f"{name} is still working; the move waits for its turn to end and never stops it"


def shells_only(info: Any) -> int:
    if info is None or getattr(info, "startup_gate", "ready") != "ready":
        return 0
    count = getattr(info, "background_open", None)
    if not isinstance(count, int) or count <= 0:
        return 0
    if info.activity_status in RESTING and info.activity_hint is not None:
        return count
    return count if info.activity_status == "working_subagent" and getattr(info, "subagents_running", None) == 0 else 0


def at_turn_end(info: Any) -> bool:
    return (info is not None and info.activity_status in RESTING and info.activity_hint is None
            and getattr(info, "startup_gate", "ready") == "ready")


async def wait_for_turn_end(find: Callable[[], Awaitable[Any]], wait_seconds: float, *, settle: float = SETTLE_SECONDS,
                            poll: float = POLL_SECONDS, name: str = "the agent",
                            on_blocker: Optional[Callable[[str], Awaitable[None]]] = None, shells_ok: bool = False) -> None:
    loop = asyncio.get_running_loop()
    deadline, rested_since, last, told = loop.time() + wait_seconds, None, None, None
    while True:
        try:
            info = await asyncio.wait_for(find(), timeout=max(0.1, min(FIND_SECONDS, deadline - loop.time())))
        except asyncio.TimeoutError:
            info = None
        last = info.activity_status if info is not None else None
        ended = at_turn_end(info) or (shells_ok and shells_only(info) > 0)
        blocker = "" if ended else blocker_text(info, name)
        if on_blocker is not None and blocker != told:
            told = blocker
            await on_blocker(blocker)
        if ended:
            rested_since = rested_since if rested_since is not None else loop.time()
            if loop.time() - rested_since >= settle:
                return
        else:
            rested_since = None
        if loop.time() + poll > deadline:
            raise TurnNotEnded(last, getattr(info, "activity_hint", None), getattr(info, "background_open", None))
        await asyncio.sleep(poll)
