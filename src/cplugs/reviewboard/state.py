
from __future__ import annotations

from typing import Optional

from src.cplugs.reviewboard.schema import Sidecar

EMPTY, YOUR_TURN, WITH_CLAUDE, UNDELIVERED = "empty", "your_turn", "with_claude", "undelivered"
LIVE = "live"
CLOSED = "closed"
STATES = (EMPTY, YOUR_TURN, WITH_CLAUDE, UNDELIVERED, LIVE, CLOSED)
TASK_DONE = "done"


def board_state(sidecar: Sidecar) -> str:
    if any(r.delivery.state == "undelivered" for r in sidecar.rounds):
        return UNDELIVERED
    if sidecar.live is not None:
        return LIVE
    if not sidecar.revisions:
        return EMPTY
    if not sidecar.rounds:
        return YOUR_TURN
    latest, round_ = sidecar.revisions[-1], sidecar.rounds[-1]
    if latest.answers_round == round_.id:
        return YOUR_TURN
    return WITH_CLAUDE if round_.sent_at >= latest.created_at else YOUR_TURN


def last_activity(sidecar: Sidecar) -> Optional[str]:
    times = [r.created_at for r in sidecar.revisions] + [r.sent_at for r in sidecar.rounds]
    if sidecar.live is not None:
        times += [sidecar.live.draft.updated_at] + [s.at for s in sidecar.live.sends]
    return max(times) if times else None


def closed_over(derived: Optional[str], task_state: Optional[str]) -> Optional[str]:
    """The state a list shows once the linked task's state is known: ``CLOSED`` when the task is done, else the sidecar's own state.

    Inputs: derived (str | None) - :func:`board_state`'s answer, None for a board that could not be read; task_state (str | None) - the
      linked task's Task Manager state, None when the board is unlinked, the task is gone or could not be read.
    Output: str | None. Example: closed_over("with_claude", "done") -> "closed"; closed_over("with_claude", "open") -> "with_claude"
    """
    if derived is None or task_state != TASK_DONE:
        return derived
    return CLOSED
