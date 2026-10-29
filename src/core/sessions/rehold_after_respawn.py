
from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


def is_held(manager: Any, name: str) -> bool:
    return any(
        getattr(backend, "tmux_session", None) == name
        for backend in manager._registry.backends.values()
    )


async def rehold_respawned_session(manager: Any, name: str) -> Optional[str]:
    from src.core.session_boot_readopt import probe_instances, readopt_surviving_sessions

    if is_held(manager, name):
        return None
    _socket, listing = probe_instances(manager)
    if not listing.ok:
        logger.warning("respawn_rehold_listing_unavailable", name=name, reason=getattr(listing, "reason", None))
        return None
    narrowed = replace(
        listing,
        sessions=[row for row in listing.sessions if isinstance(row, dict) and row.get("name") == name],
    )
    report = await readopt_surviving_sessions(manager, narrowed)
    held = list(getattr(report, "held", []) or [])
    logger.info("respawn_rehold", name=name, held=len(held), failed=len(getattr(report, "failed", []) or []),
                outcome=getattr(report, "outcome", None))
    return held[0] if held else None
