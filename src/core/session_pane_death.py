
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
