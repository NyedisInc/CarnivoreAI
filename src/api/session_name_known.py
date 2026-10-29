"""Whether a tmux name is one of ours, for the routes keyed on a NAME.

Most session routes are addressed by session id and resolve a row. A few
are addressed by the bare tmux NAME instead, because the value they write
is keyed on the name and outlives the row: the theme pin
(``pinned_themes.json``) and the terminal background override
(``session_backgrounds.json``). Those two have to answer for a session that
is detached but alive, which no row lookup would find.

THE COST OF THAT IS THAT THE KEY IS CALLER-SUPPLIED, so each of them must
refuse a name it does not recognise or it becomes an arbitrary key-value
store with a JSON file behind it. The recognised set is the union of three
independent readings - the names this app has ever created, the names it is
currently driving, and the names tmux says are attachable right now -
because each of the three misses sessions the other two see.

**A FAILED PROBE ONLY SHRINKS THE SET.** The union already contains the
owned ledger and every live backend, so a tmux probe that could not run
costs at most a 404 on a name nobody could confirm: a refusal, never a
silent write to the wrong key. It is logged, because a degraded input that
narrows an authorisation decision has to be visible.

THIS WAS LIFTED OUT OF ``session_theme_routes`` RATHER THAN COPIED. The two
routes have to agree on what a known session is - they are keyed on the same
string and written from the same control - and two spellings of one
authorisation check is one of them getting widened later on its own.
"""

from __future__ import annotations

from typing import Any, Set

import structlog

from src.core.tmux_listing import coerce_listing

logger = structlog.get_logger()

ADOPTED_PREFIX = "adopted:"


def strip_adopted_prefix(session_name: str) -> str:
    if session_name.startswith(ADOPTED_PREFIX):
        return session_name[len(ADOPTED_PREFIX):]
    return session_name


def known_tmux_names(session_manager: Any, owned_tmux: Any) -> Set[str]:
    names: Set[str] = set(owned_tmux.names)
    names |= session_manager.active_tmux_names()
    try:
        listing = coerce_listing(session_manager.list_attachable_sessions())
        if not listing.ok:
            logger.warning(
                "session_name_attachable_probe_unavailable",
                reason=listing.reason,
            )
        names |= set(listing.names)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("session_name_attachable_probe_failed", error=str(exc))
    return names
