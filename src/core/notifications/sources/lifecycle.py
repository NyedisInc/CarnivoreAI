
from __future__ import annotations

import asyncio
from typing import Any, Optional

from src.core.notifications.sources import agent_update, alerts


def start(app_state: Any, loop: asyncio.AbstractEventLoop) -> None:
    alerts.install(loop)
    agent_update.install(lambda: getattr(app_state, "attention_watcher", None))


async def stop(task: Optional["asyncio.Task[None]"] = None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
