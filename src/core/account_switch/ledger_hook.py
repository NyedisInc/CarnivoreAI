"""What runs after a ledger pass that moved a reading (issues #151, #521, #671).

Three consumers, in this order. :mod:`profile_setup` first brings every
managed claude profile whose login reads ``ok`` to a launchable state
(first-run setup marked done, the shared MCP file synced and the profile's
copies of it removed, folder trust copied), so
the two after it see the accounts as they will be launched onto. Then
auto-switch moves a provider's pointer (:mod:`auto_switch`, which never
touches a session), then the restart pass restarts claude sessions blocked
on their account's limit onto the (now current) active account
(:mod:`auto_restart`). The last two are no-ops unless the auto-switch toggle
is on; the first runs whatever the toggle says, because a manual switch and
a new session need a ready profile too. Kept apart so the module that only
moves a pointer keeps no route to a session at all.
"""

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
