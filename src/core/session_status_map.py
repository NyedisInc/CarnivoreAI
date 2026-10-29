
from __future__ import annotations

from typing import Any, Dict, Optional


class StatusMap(dict):

    complete: bool = False

    socket: Optional[str] = None

    def __init__(
        self,
        rows: Optional[Dict[str, Any]] = None,
        *,
        complete: bool = False,
        socket: Optional[str] = None,
    ) -> None:
        super().__init__(rows or {})
        self.complete = bool(complete)
        self.socket = socket or None


def listing_proves_alive(
    status_map: Optional[Dict[str, Any]],
    tmux_name: Optional[str],
    *,
    backend_socket: Optional[str] = None,
) -> bool:
    if not tmux_name:
        return False
    if status_map is None:
        return False
    if not getattr(status_map, "complete", False):
        return False
    listing_socket = getattr(status_map, "socket", None)
    if not listing_socket or not backend_socket:
        return False
    if listing_socket != backend_socket:
        return False
    return tmux_name in status_map


def status_map_from_listing(
    listing: Any, *, socket: Optional[str]
) -> "StatusMap":
    if not getattr(listing, "ok", False):
        return StatusMap()
    return StatusMap(
        {
            row["name"]: row
            for row in getattr(listing, "sessions", None) or []
            if isinstance(row, dict) and row.get("name")
        },
        complete=bool(getattr(listing, "complete", False)),
        socket=socket,
    )
