"""The one usage poller this process runs, and how it is reached.

WHY BOOT DOES NOT WAIT. :func:`start` creates a task and returns, the
same posture ``src/core/corpus_ingest_task.py`` states and for the same
reason: uvicorn binds at the lifespan's ``yield``, so a pass awaited
there would hold the port closed for as long as two providers take to
answer. Nothing on the startup path awaits a poll, and a poll that fails
resolves to a named state on a row rather than to an exception.

THE TICK IS A FLOOR, NOT A PERIOD. The five second sleep happens AFTER a
scan finishes, so a scan that runs long cannot stack up behind itself.
The tick is not a poll interval and it is not the rate limit: a scan
usually polls nothing at all. Each account carries its own
``next_poll_at`` and the scan is only the thing that notices one is due.

THE RATE BUDGET IS PER IDENTITY, NOT PER ROW. The Claude usage endpoint
admits roughly 28 to 30 requests per hour per identity, and capacity
returns only as old requests age out of a trailing hour rather than at a
refill rate. Three accounts pointing at three different logins are three
separate budgets and are safe at this floor. TWO ROWS POINTING AT ONE
LOGIN SHARE ONE BUDGET and will burn it at twice the rate, which is the
user's configuration to avoid: two config dirs can hold the same
identity and nothing short of a request would tell this module so.

IT READS THE CREDENTIAL STORE, IT NEVER WRITES ONE AND NEVER REFRESHES.
Both providers rotate refresh tokens and OpenAI detects reuse, so a
refresh performed here would invalidate the copy the user's own CLI
holds. An expired login is a REPORTED STATE until ``claude`` or
``codex`` renews it themselves, and a credential that cannot work is
answered locally without spending a request to be told so.

THE ACCOUNT LIST IS RE-READ EVERY PASS. A row added through
``PUT /api/v1/provider-ledger/accounts/{id}`` is polled on the next tick
with no restart, and a row removed there takes its readings with it: a
row for a deleted account would be a number nobody can refresh and
nobody can delete.

NO TOKEN, HEADER OR BODY REACHES A LOG LINE FROM THIS FEATURE. Every
event carries an account id, a provider, a state and at most a
status-shaped string. ``tests/test_provider_ledger_poller.py`` searches
whole captured records rather than named fields, because a credential
escapes through whichever kwarg somebody added last.

THE LOOP LIVES IN :mod:`poller_core` and one account's state in
:mod:`poller_state`; this module is the process-wide instance and the
four calls the lifespan and the routes make.
"""

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
    """Start the 15 second limit-stop restart timer beside the loop (issue #672).

    Description: imported late, because the switch package reads this one.
      Idempotent: a timer already running is left as it is.
    Inputs: app_state (Any).
    Output: None.
    """
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
    """Tell the process-wide poller one account no longer exists.

    Description: what the removal route calls, so the ledger stops
      answering a row for an account the file no longer holds instead of
      answering one until the next pass. A no-op when no loop is
      running, because there is then nothing remembering it.
    Inputs: account_id (str).
    Output: None.
    Example: forget_account("max-main")
    """
    if _POLLER is not None:
        _POLLER.forget_account(account_id)
