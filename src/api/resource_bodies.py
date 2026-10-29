
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from src.api import computers_routes, pack_machines_routes
from src.core.resource_push import bodies, topics
from src.core.stats_feed import install as stats_feed


async def _computers() -> Optional[Any]:
    try:
        return await computers_routes.get_computers(None)  # type: ignore[arg-type]
    except HTTPException:
        return None


async def _pack_machines() -> Optional[Any]:
    try:
        return await pack_machines_routes.machines_view()
    except HTTPException:
        return None


def register(app_state: Any) -> None:
    bodies.register("computers", [topics.COMPUTERS, topics.PACK_MACHINES], _computers)
    bodies.register("pack_machines", [topics.PACK_MACHINES], _pack_machines)

    async def stats() -> Optional[Any]:
        return stats_feed(app_state).push_body()

    bodies.register("stats_feed", [topics.STATS_FEED], stats)
