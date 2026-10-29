
from __future__ import annotations

from typing import Any, List, Optional

import structlog

from src.core.spectator_links_store import SpectatorLink, SpectatorLinksStore

logger = structlog.get_logger()


def notify_revoked(lifecycle: Optional[Any]) -> None:
    if lifecycle is None:
        return
    publisher = lifecycle.publisher
    if publisher is not None and publisher.connected:
        publisher.poke()
    lifecycle.schedule_stop_check()


async def revoke_all_live(store: Optional[SpectatorLinksStore], lifecycle: Optional[Any]) -> List[SpectatorLink]:
    if store is None:
        return []
    live = await store.list_live()
    for link in live:
        await store.revoke(link.id)
    if live:
        logger.info("spectator_links_revoked_all", count=len(live))
        notify_revoked(lifecycle)
    return live
