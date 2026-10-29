
from __future__ import annotations

import asyncio
from typing import Any, Set

import structlog

from src.core.account_switch import auto_restart, auto_switch, profile_setup
from src.models.provider_ledger import LedgerSnapshot

logger = structlog.get_logger()


_TASKS: Set["asyncio.Task[Any]"] = set()


def _done(task: "asyncio.Task[Any]") -> None:
    _TASKS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("limit_rotation_pass_failed", error=type(task.exception()).__name__)


async def after_ledger_pass(snapshot: LedgerSnapshot, app_state: Any = None) -> None:
    await profile_setup.after_pass(snapshot, app_state)
    await auto_switch.after_pass(snapshot, app_state)
    task = asyncio.create_task(auto_restart.after_pass(snapshot, app_state))
    _TASKS.add(task)
    task.add_done_callback(_done)
