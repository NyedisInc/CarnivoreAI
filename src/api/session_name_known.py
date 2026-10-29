
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
