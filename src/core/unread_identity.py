
from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Optional

import structlog

logger = structlog.get_logger()

EPOCH_FIELD = "created_at_epoch"
NAME_FIELD = "name"

EpochCache = MutableMapping[str, int]
ListingProbe = Callable[[], Any]


def epoch_of_row(row: Optional[Mapping[str, Any]]) -> Optional[int]:
    if not row:
        return None
    raw = row.get(EPOCH_FIELD)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.debug("unread_epoch_uncoercible", value=repr(raw))
        return None


def remember(
    cache: EpochCache, tmux_name: Optional[str], epoch: Optional[int]
) -> Optional[int]:
    if tmux_name and epoch is not None:
        cache[tmux_name] = int(epoch)
    return epoch


def remember_listing(cache: EpochCache, listing: Any) -> int:
    if not getattr(listing, "ok", False):
        return 0
    seen = 0
    for row in getattr(listing, "sessions", None) or []:
        if remember(cache, row.get(NAME_FIELD), epoch_of_row(row)) is not None:
            seen += 1
    return seen


def resolve_epoch(
    cache: EpochCache,
    tmux_name: Optional[str],
    probe: Optional[ListingProbe] = None,
) -> Optional[int]:
    if not tmux_name:
        return None
    cached = cache.get(tmux_name)
    if cached is not None:
        return cached
    if probe is None:
        return None
    try:
        listing = probe()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.debug("unread_epoch_probe_failed", error=str(exc))
        return None
    remember_listing(cache, listing)
    return cache.get(tmux_name)


def forget(cache: EpochCache, tmux_name: Optional[str]) -> None:
    if tmux_name:
        cache.pop(tmux_name, None)
