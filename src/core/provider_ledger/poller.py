
from __future__ import annotations

import os
from typing import Any, Optional

import structlog

from src.core.provider_ledger.poller_core import LedgerPoller
from src.models.provider_ledger import LedgerSnapshot, LedgerTotal, LoopStatus

logger = structlog.get_logger()

TEST_MODE_ENV = "CLOUDE_TEST_MODE"

__all__ = [
    "LedgerPoller",
    "start",
    "stop",
    "snapshot",
    "poll_soon",
    "forget_account",
    "TEST_MODE_ENV",
]


_POLLER: Optional[LedgerPoller] = None

_RESTART_TIMER: Optional[Any] = None


def start(app_state: Any = None) -> bool:
    global _POLLER
    if os.environ.get(TEST_MODE_ENV):
        logger.info("provider_ledger_poller_not_started_under_test_mode")
        return False
    if _POLLER is None:
        _POLLER = LedgerPoller(app_state=app_state)
    started = _POLLER.start()
    _start_restart_timer(app_state)
    return started


def _start_restart_timer(app_state: Any) -> None:
    global _RESTART_TIMER
    from src.core.account_switch.restart_timer import RestartTimer

    if _RESTART_TIMER is None:
        _RESTART_TIMER = RestartTimer(app_state=app_state, snapshot=snapshot)
    _RESTART_TIMER.start()


async def stop() -> None:
    global _POLLER, _RESTART_TIMER
    timer, _RESTART_TIMER = _RESTART_TIMER, None
    if timer is not None:
        await timer.stop()
    if _POLLER is None:
        return
    await _POLLER.stop()
    _POLLER = None


def snapshot() -> LedgerSnapshot:
    if _POLLER is None:
        return LedgerSnapshot(
            accounts=[],
            total=LedgerTotal(accounts=0),
            loop=LoopStatus(alive=False),
        )
    return _POLLER.snapshot()


def poll_soon(account_id: str) -> None:
    if _POLLER is not None:
        _POLLER.poll_soon(account_id)


def forget_account(account_id: str) -> None:
    if _POLLER is not None:
        _POLLER.forget_account(account_id)
