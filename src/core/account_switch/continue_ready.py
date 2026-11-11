
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from src.core.approvals.extract import extract_dialog
from src.core.attention.screen_read import capture_screen
from src.core.session_startup_gate import startup_screen_kind
from src.core.tmux_one_shot import input_box_text

SETTLE_SECONDS = 3.0

Capture = Callable[[], Awaitable[Optional[str]]]


def shows_empty_prompt(screen: Optional[str]) -> bool:
    if not screen:
        return False
    if extract_dialog(screen, "claude") is not None or startup_screen_kind(screen) is not None:
        return False
    return input_box_text(screen.encode("utf-8")) == ""


def _capturer(manager: Any, tmux_name: str) -> Capture:
    async def capture() -> Optional[str]:
        return await asyncio.to_thread(capture_screen, manager.tmux_socket_name(), tmux_name)

    return capture


async def at_empty_prompt(manager: Any, info: Any, *, capture: Optional[Capture] = None) -> bool:
    return shows_empty_prompt(await (capture or _capturer(manager, info.tmux_session))())


async def settled_at_empty_prompt(
    manager: Any, info: Any, *, settle: float = SETTLE_SECONDS, capture: Optional[Capture] = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> bool:
    read = capture or _capturer(manager, info.tmux_session)
    first = await read()
    if not shows_empty_prompt(first):
        return False
    await sleep(settle)
    return await read() == first
