
from __future__ import annotations

import asyncio
from typing import Any, NamedTuple, Optional, Tuple

import structlog

logger = structlog.get_logger()

SETTLE_SECONDS: float = 0.15

REASON_CONFIRMED_UNCHANGED: str = "geometry_confirmed_unchanged"

REASON_CHANGED: str = "geometry_changed"

# could not
REASON_UNMEASURED: str = "geometry_unmeasured"

REASON_NO_CLIENT_GEOMETRY: str = "no_client_geometry"

REASON_RESIZE_FAILED: str = "resize_failed"


class ResizeOutcome(NamedTuple):

    target: Optional[Tuple[int, int]]
    issued: bool
    failed: bool


NO_RESIZE_ATTEMPTED: ResizeOutcome = ResizeOutcome(
    target=None, issued=False, failed=False
)


class SettleVerdict(NamedTuple):

    settle: bool
    reason: str


def decide_settle(
    measured: Optional[Tuple[int, int]],
    outcome: ResizeOutcome,
) -> SettleVerdict:
    """Decide whether the attach handshake must pause before painting.

    The ladder, in order. Only the last rung skips:

    Args:
        measured: (cols, rows) the PANE reported for itself before the
            resize, or None when it could not be read.
        outcome: what the resize attempt actually did.

    Returns:
        SettleVerdict: ``settle`` plus the reason it was decided.

    Example:
        >>> decide_settle((100, 40), ResizeOutcome((100, 40), False, False))
        SettleVerdict(settle=False, reason='geometry_confirmed_unchanged')
        >>> decide_settle(None, ResizeOutcome((100, 40), True, False))
        SettleVerdict(settle=True, reason='geometry_unmeasured')
    """
    if outcome.failed:
        return SettleVerdict(True, REASON_RESIZE_FAILED)
    if outcome.target is None:
        return SettleVerdict(True, REASON_NO_CLIENT_GEOMETRY)
    if measured is None:
        return SettleVerdict(True, REASON_UNMEASURED)
    if outcome.issued:
        return SettleVerdict(True, REASON_CHANGED)
    if tuple(measured) != tuple(outcome.target):
        return SettleVerdict(True, REASON_CHANGED)
    return SettleVerdict(False, REASON_CONFIRMED_UNCHANGED)


async def read_pane_geometry(backend: Any) -> Optional[Tuple[int, int]]:
    if backend is None:
        return None
    probe = getattr(backend, "pane_geometry", None)
    if probe is None:
        return None
    try:
        result = probe()
        if asyncio.iscoroutine(result):
            result = await result
    except (OSError, ValueError, RuntimeError) as exc:
        logger.debug("pane_geometry_probe_failed", error=str(exc))
        return None
    if result is None:
        return None
    try:
        cols, rows = result
        return (int(cols), int(rows))
    except (TypeError, ValueError):
        logger.debug("pane_geometry_probe_unparseable", value=repr(result))
        return None


async def settle_if_needed(verdict: SettleVerdict) -> None:
    if verdict.settle:
        await asyncio.sleep(SETTLE_SECONDS)
