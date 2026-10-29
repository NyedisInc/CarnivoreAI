
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Tuple

PendingMap = Dict[str, Tuple[str, asyncio.Event]]


@asynccontextmanager
async def hold_pending_registration(
    pending: PendingMap, session_id: str, tmux_name: str
) -> AsyncIterator[None]:
    event = asyncio.Event()
    entry = (tmux_name, event)
    pending[session_id] = entry
    try:
        yield
    finally:
        if pending.get(session_id) is entry:
            pending.pop(session_id, None)
        event.set()
