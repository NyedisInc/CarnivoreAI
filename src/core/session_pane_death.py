"""Is this session's PANE measured dead? The gate the husk reaper rests on.

THE GATE, AND THE ASYMMETRY IN IT, WHICH IS THE WHOLE DESIGN.

A reap is DURABLE and USER-VISIBLE. A wrong one takes a session the user
is working in out of their running list, and afterwards it is
indistinguishable from a measurement. So this answers :data:`PANE_DEAD`
ONLY on a positively measured ``#{pane_dead}`` of ``"1"``, read out of a
COMPLETE pane listing taken from the SOCKET THE BACKEND IS BOUND TO, for a
row whose creation epoch matches the one the stored session claims.
EVERYTHING else is :data:`PANE_UNKNOWN` and reaps nothing: no listing at
all, an incomplete one, an unstated or mismatched socket, a name the
listing does not carry, a row that is not a readable mapping, an epoch
that is absent or unreadable or belongs to a different instance, and a
``pane_dead`` field that is missing or is any text other than ``"0"`` or
``"1"``.

REFUSING IS FREE AND REAPING WRONGLY IS NOT. Every refusal above leaves
the row exactly as it was, which is the behaviour that shipped before this
module existed - so an over-eager refusal costs nothing at all, while one
over-eager reap costs a live session. That is the same trade
``listing_proves_alive`` makes for the positive half of the same listing,
and the same one ``session_recreate_presence`` makes for ``gone``.

THE EPOCH IS NOT OPTIONAL, AND IT IS THE HALF THAT IS EASY TO DROP. The
pane listing is keyed by tmux NAME, and a name is not an identity in this
app - it is minted from a project slug and re-minted every time a session
is recreated. Match on the name alone and a brand new ``cloude_work``,
alive and being typed into, inherits the verdict measured on the corpse
that held that name a minute ago. ``list_pane_status_all`` already carries
``#{session_created}`` for exactly this reason, so the check costs nothing
but a comparison and is required rather than advisory: a row that cannot
supply a readable epoch answers :data:`PANE_UNKNOWN`.

NO NEW SUBPROCESS, BY CONSTRUCTION. Nothing here shells out. The caller
hands in a listing that the launcher's pass was already paying for
(``TmuxBackend.list_pane_status_all``, one ``tmux list-panes -a``, whose
format string has carried ``#{pane_dead}`` since it shipped), so this rung
adds no tmux call of its own. If a future change finds itself probing tmux
to answer this question, the answer belongs in that existing listing
instead.

WHAT IT DOES NOT DECIDE. Whether a dead pane's tmux HUSK should be killed
to free its name. That is a separate, destructive act needing its own
authorization, and ``remain-on-exit`` exists to preserve exactly what
killing it would destroy. This module measures; it does not clean up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from src.core.session_respawn import PANE_ALIVE, PANE_DEAD, PANE_UNKNOWN

PANE_DEAD_TRUE: str = "1"

PANE_DEAD_FALSE: str = "0"

LIFECYCLE_SOURCE_PANE_DEAD: str = "pane_dead"


@dataclass(frozen=True)
class PaneDeath:

    outcome: str
    detail: str = ""
    pane_dead_raw: Optional[str] = None

    @property
    def dead(self) -> bool:
        return self.outcome == PANE_DEAD


def _unknown(detail: str, raw: Optional[str] = None) -> PaneDeath:
    """Build the COULD NOT EVALUATE result, the only shape a refusal has.

    Description: a named constructor so the nine refusal rungs cannot
      accidentally differ from one another, and so none of them can grow
      a field that would read as a measurement.
    Inputs: detail (str) - why we could not answer. raw (str | None) - the
      ``#{pane_dead}`` text, when one was actually reached.
    Output: PaneDeath with ``outcome=PANE_UNKNOWN``.
    Example: _unknown('no pane listing was supplied')
    """
    return PaneDeath(outcome=PANE_UNKNOWN, detail=detail, pane_dead_raw=raw)


def pane_death(
    pane_status: Optional[Mapping[str, Any]],
    tmux_name: Optional[str],
    created_epoch: Optional[int],
    *,
    backend_socket: Optional[str] = None,
) -> PaneDeath:
    if pane_status is None:
        return _unknown("no pane listing was taken on this pass")
    if not getattr(pane_status, "complete", False):
        return _unknown("the pane listing is not a complete enumeration")
    listing_socket = getattr(pane_status, "socket", None)
    if not listing_socket or not backend_socket:
        return _unknown("the pane listing or the caller did not state a socket")
    if listing_socket != backend_socket:
        return _unknown(
            f"the pane listing came from socket {listing_socket!r}, "
            f"not from {backend_socket!r}"
        )
    if not tmux_name:
        return _unknown("the stored row carries no tmux name")
    if isinstance(created_epoch, bool) or not isinstance(created_epoch, int):
        return _unknown("the stored row carries no readable creation epoch")
    row = pane_status.get(tmux_name)
    if row is None:
        return _unknown("the pane listing does not carry this session name")
    if not isinstance(row, dict):
        return _unknown("the pane listing row is not a readable mapping")
    row_epoch = row.get("created_at_epoch")
    if isinstance(row_epoch, bool) or not isinstance(row_epoch, int):
        return _unknown("the pane listing row carries no readable creation epoch")
    if int(row_epoch) != int(created_epoch):
        return _unknown(
            f"the pane listing row is instance {int(row_epoch)}, "
            f"not {int(created_epoch)}"
        )
    raw = row.get("pane_dead")
    if not isinstance(raw, str):
        return _unknown("the pane listing row carries no pane_dead field")
    value = raw.strip()
    if value == PANE_DEAD_TRUE:
        return PaneDeath(
            outcome=PANE_DEAD,
            detail="tmux reports this instance's pane dead",
            pane_dead_raw=value,
        )
    if value == PANE_DEAD_FALSE:
        return PaneDeath(
            outcome=PANE_ALIVE,
            detail="tmux reports this instance's pane running",
            pane_dead_raw=value,
        )
    return _unknown(f"pane_dead was {raw!r}, which is neither '0' nor '1'", raw)
