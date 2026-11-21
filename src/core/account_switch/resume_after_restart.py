from __future__ import annotations

import asyncio
from typing import Any, Optional, Set

import structlog

from src.core.mcp.beast_mode import beast_enabled
from src.core.session_delivery import bring_up
from src.core.session_startup_gate import GATE_READY
from src.core.sessions import guarded_paste
from src.core.sessions.guarded_paste import GateOptions, PasteRefused

logger = structlog.get_logger(__name__)

RESUME_WORD = "resume"
SETTLE_S = 5.0
READY_TIMEOUT_S = 600.0
READY_STEP_S = 2.0
_NOT_READY = frozenset({"question", "dead"})
ATTEMPTS = 4
RETRY_S = 5.0

_TASKS: Set["asyncio.Task[None]"] = set()


def schedule_text(app_state: Any, tmux_name: str, text: str) -> None:
    task = asyncio.get_running_loop().create_task(resume_when_ready(app_state, tmux_name, text=text))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def schedule(app_state: Any, tmux_name: str) -> bool:
    if not beast_enabled():
        return False
    schedule_text(app_state, tmux_name, RESUME_WORD)
    return True


async def _wait_started(app_state: Any, tmux_name: str, timeout: float, step: float) -> Optional[str]:
    ops = bring_up.ops_for_app(app_state)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        for info in await ops.list():
            if (info.tmux_session == tmux_name and info.startup_gate == GATE_READY
                    and info.activity_status not in _NOT_READY):
                return info.session.id
        if loop.time() + step > deadline:
            return None
        await asyncio.sleep(step)


async def resume_when_ready(app_state: Any, tmux_name: str, *, text: str = RESUME_WORD, settle: float = SETTLE_S,
                            retry: float = RETRY_S, timeout: float = READY_TIMEOUT_S, step: float = READY_STEP_S) -> bool:
    await asyncio.sleep(settle)
    session_id = await _wait_started(app_state, tmux_name, timeout, step)
    if session_id is None:
        logger.warning("resume_after_restart_not_ready", name=tmux_name, waited_s=timeout)
        return False
    for attempt in range(1, ATTEMPTS + 1):
        try:
            await guarded_paste.paste_through_gates(app_state, session_id, text, GateOptions(fresh_dialog_check=True, hold_exempt=True))
        except PasteRefused as exc:
            logger.info("resume_after_restart_refused", name=tmux_name, attempt=attempt, detail=exc.message)
            if attempt < ATTEMPTS:
                await asyncio.sleep(retry)
            continue
        logger.info("resume_after_restart_sent", name=tmux_name, session_id=session_id)
        return True
    return False
