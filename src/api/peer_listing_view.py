
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

from src.api import peer_auth
from src.api.session_crud_routes import build_owner_listing
from src.api.session_sleep_routes import _peer_asleep_rows
from src.core.federation import peer_listing


async def peer_view(app_state: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    infos = await peer_listing.for_caller(await build_owner_listing(app_state), is_peer=True, open_db=peer_auth.open_db)
    rows = await asyncio.to_thread(lambda: [i.model_dump(mode="json") for i in infos])
    return rows, await _peer_asleep_rows()
