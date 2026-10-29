"""The one seam between the listing pass and the permission-pane check.

Everything that needs tmux or mutable state happens here; the ladder and the
matcher stay pure in ``session_permission_verify`` and are tested without a
tmux server. Same split, and the same reasons, as
``session_startup_gate`` / ``SessionManager._startup_gate_for``.

IT RUNS BEFORE ``resolve()``, NOT AFTER. A verdict computed after the status
string was built would need the status recomputing or patching, and a patched
status is a second place that decides what the light says. Clearing the flag
first means ``SessionActivityTracker.resolve`` sees the corrected state and
produces the answer on its own, so there is still exactly one resolver.

NEVER RAISES. A listing poll must not fail because one pane could not be read,
and a permission light is not worth a 500 on the home screen.

STEADY STATE COSTS NOTHING, AND THAT WAS CHECKED RATHER THAN CLAIMED.
``should_capture_permission_tail`` is FAIL-CLOSED at every refusal: a session
with no open claim and no stamp is refused, so a box with no dialog on any
pane spends no subprocess here at all. That is the opposite of the startup
gate's equivalent refusal, which was fail-OPEN and cost 13 of 13 healthy
sessions a capture per poll. The one cost that WAS real is the re-look - both
verdicts that keep the flag leave the gate passing next poll - and
``session_permission_verify_ledger`` bounds it without touching the first
look at any claim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import structlog

from src.core.session_permission_verify import (
    PERMISSION_CLEARED_NO_DIALOG,
    PERMISSION_CLEARED_PANE_DEAD,
    PERMISSION_NOT_CHECKED,
    PERMISSION_TAIL_LINES,
    resolve_permission_check,
    should_capture_permission_tail,
)
from src.core.session_permission_verify_ledger import ledger_for

logger = structlog.get_logger(__name__)

_VERIFY_ERRORS = (OSError, ValueError, TypeError, AttributeError)


def verify_open_permission(
    manager: Any,
    *,
    session_id: str,
    backend: Any,
    tmux_name: Optional[str],
    pane_alive: Optional[bool],
    now: Optional[datetime] = None,
) -> str:
    tracker = getattr(manager, "_activity_tracker", None)
    if tracker is None or not tmux_name:
        return PERMISSION_NOT_CHECKED

    now = now or datetime.utcnow()

    try:
        opened_at = tracker.permission_open_since(session_id)

        if pane_alive is False:
            if opened_at is not None and tracker.clear_permission(session_id):
                logger.info(
                    "permission_flag_cleared_pane_dead",
                    session_id=session_id,
                    tmux_name=tmux_name,
                    open_seconds=round(
                        (now - opened_at).total_seconds(), 1
                    ),
                )
                return PERMISSION_CLEARED_PANE_DEAD
            return PERMISSION_NOT_CHECKED

        ledger = ledger_for(manager)
        if not should_capture_permission_tail(
            pane_alive=pane_alive,
            permission_open=opened_at is not None,
            opened_at=opened_at,
            now=now,
            last_check_at=ledger.last_check_at(session_id, opened_at),
        ):
            return PERMISSION_NOT_CHECKED

        socket_name = getattr(backend, "socket_name", None)
        if not socket_name:
            return PERMISSION_NOT_CHECKED

        from src.core.session_startup_gate_ledger import capture_pane_tail

        tail = capture_pane_tail(
            socket=socket_name, name=tmux_name, lines=PERMISSION_TAIL_LINES
        )
        ledger.record_check(session_id, opened_at, now=now)
        verdict = resolve_permission_check(captured=True, tail=tail)

        if verdict == PERMISSION_CLEARED_NO_DIALOG:
            if tracker.clear_permission(session_id):
                logger.info(
                    "permission_flag_cleared_no_dialog",
                    session_id=session_id,
                    tmux_name=tmux_name,
                    open_seconds=round(
                        (now - opened_at).total_seconds(), 1
                    ),
                )
        return verdict
    except _VERIFY_ERRORS as exc:
        logger.warning(
            "permission_verify_failed",
            session_id=session_id,
            tmux_name=tmux_name,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return PERMISSION_NOT_CHECKED
