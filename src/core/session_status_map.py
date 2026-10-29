
from __future__ import annotations

from typing import Any, Dict, Optional


class StatusMap(dict):
    """``{tmux_session_name: pane row}`` plus whether the listing is whole.

    ``complete`` is True only when the bulk ``list-panes -a`` probe ran
    and returned a real answer - INCLUDING a real answer of zero sessions
    (``reason='no_server'``), which is a measurement and not a failure.
    It is False when the probe could not run, in which case the listing
    cannot vouch for anything at all.
    """

    complete: bool = False

    socket: Optional[str] = None

    def __init__(
        self,
        rows: Optional[Dict[str, Any]] = None,
        *,
        complete: bool = False,
        socket: Optional[str] = None,
    ) -> None:
        """Build the map.

        Inputs:
            rows: ``{tmux_session_name: row}``; empty when the listing
                found nothing or could not run.
            complete: True iff the listing ran and its enumeration of
                live session names can be trusted.
            socket: the tmux socket the listing was taken from. None
                means "not stated", which makes the map unable to prove
                anything about any backend.
        Output: None.
        Example:
            >>> StatusMap(
            ...     {"cloude_a": {"status": "running"}},
            ...     complete=True,
            ...     socket="cloude",
            ... )
            {'cloude_a': {'status': 'running'}}
        """
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
    """Index one ``list-panes -a`` result by session name, with provenance.

    Description: the single place a pane listing becomes a
      :class:`StatusMap`, so the two facts that make the map usable as
      EVIDENCE - whether the enumeration is whole, and which socket it
      came from - are attached by one rule rather than restated at every
      construction site. A listing that did not answer yields an EMPTY map
      stating neither, which every consumer already reads as "cannot
      vouch" and falls back from.
    Inputs:
        listing: a ``TmuxListing`` from ``list_pane_status_all``. Typed
            loosely on purpose so this module keeps no import edge to
            ``tmux_listing``; only ``.ok``, ``.complete`` and ``.sessions``
            are read.
        socket: the socket the probe that produced the listing was
            ACTUALLY bound to, read off the probe rather than re-derived
            from settings, so the map can never claim a socket the listing
            did not come from. None means "not stated", which makes the
            map unable to prove anything.
    Output:
        StatusMap - rows keyed by tmux session name.
    Example:
        >>> class L:
        ...     ok = True
        ...     complete = True
        ...     sessions = [{"name": "cloude_a", "pane_dead": "0"}]
        >>> status_map_from_listing(L(), socket="cloude").complete
        True
    """
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
