
from __future__ import annotations

import asyncio
from typing import Any, Set

import structlog

from src.core.tmux_listing import coerce_listing

logger = structlog.get_logger()

ADOPTED_PREFIX = "adopted:"


def strip_adopted_prefix(session_name: str) -> str:
    if session_name.startswith(ADOPTED_PREFIX):
        return session_name[len(ADOPTED_PREFIX):]
    return session_name


def merge_attachable_names(names: Set[str], listing_source: Any) -> Set[str]:
    try:
        listing = coerce_listing(listing_source.list_attachable_sessions())
        if not listing.ok:
            logger.warning(
                "session_name_attachable_probe_unavailable",
                reason=listing.reason,
            )
        return names | set(listing.names)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("session_name_attachable_probe_failed", error=str(exc))
    return set(names)


def _owned_and_active_names(session_manager: Any, owned_tmux: Any) -> Set[str]:
    names: Set[str] = set(owned_tmux.names)
    names |= session_manager.active_tmux_names()
    return names


def known_tmux_names(session_manager: Any, owned_tmux: Any) -> Set[str]:
    return merge_attachable_names(_owned_and_active_names(session_manager, owned_tmux), session_manager)


async def known_tmux_names_async(session_manager: Any, owned_tmux: Any) -> Set[str]:
    names = _owned_and_active_names(session_manager, owned_tmux)
    return await asyncio.to_thread(merge_attachable_names, names, session_manager)
