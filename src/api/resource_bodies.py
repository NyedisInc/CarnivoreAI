
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from src.api import computers_routes, pack_machines_routes, provider_ledger_routes
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


async def _provider_ledger() -> Optional[Any]:
    try:
        snap = await provider_ledger_routes.get_provider_ledger()
        return snap.model_dump(mode="json")
    except Exception:  # noqa: BLE001
        return None


def register(app_state: Any) -> None:
    bodies.register("computers", [topics.COMPUTERS, topics.PACK_MACHINES], _computers)
    bodies.register("pack_machines", [topics.PACK_MACHINES], _pack_machines)
    bodies.register("provider_ledger", [topics.PROVIDER_LEDGER], _provider_ledger)

    async def stats() -> Optional[Any]:
        return stats_feed(app_state).push_body()

    bodies.register("stats_feed", [topics.STATS_FEED], stats)
