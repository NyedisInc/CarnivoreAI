
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.api import peer_auth
from src.api.error_response import api_error
from src.api.pack_removed_logins_routes import mesh_route, owner_only
from src.core.pack.meshdata import star_era
from src.core.pack.relay import member_reach

router = APIRouter(prefix="/pack/leftovers", tags=["pack-relay"])


def _read() -> Dict[str, Any]:
    held = member_reach.held_v2()
    if held is None:
        return {"known": False, "leftovers": []}
    with closing(peer_auth.open_db()) as conn:
        return {"known": True, "leftovers": star_era.describe(conn, held)}


def _forget(install_id: str) -> None:
    held = member_reach.held_v2()
    if held is None:
        raise LookupError("no held list")
    with closing(peer_auth.open_db()) as conn:
        star_era.forget(conn, held, install_id)


@router.get("", dependencies=[Depends(mesh_route), Depends(owner_only("leftovers_owner_only"))])
async def list_leftovers() -> Dict[str, Any]:
    """The stats this computer still holds for computers that are gone from the Pack.

    Example: GET /api/v1/pack/leftovers -> {"known": true, "leftovers": [{"install_id": "iid-a", "name": "old mac", "newest_at": 1.7e9, "rows": {"usage": 12, "counters": 30, "projects": 2, "groups": 12}}]}"""
    try:
        return await asyncio.to_thread(_read)
    except (sqlite3.Error, OSError) as exc:
        raise api_error(503, "leftovers_unavailable", exc) from exc


@router.delete("/{install_id}", dependencies=[Depends(mesh_route), Depends(owner_only("leftovers_owner_only"))])
async def forget_leftover(install_id: str) -> Dict[str, Any]:
    """Forget one leftover computer's stats (the owner's click; no MCP tool). 409 when it is not a leftover now.

    Example: DELETE /api/v1/pack/leftovers/iid-a -> {"forgotten": "iid-a"}"""
    try:
        await asyncio.to_thread(_forget, install_id)
    except LookupError as exc:
        raise api_error(409, "leftovers_list_unknown", exc) from exc
    except star_era.NotLeftover as exc:
        raise api_error(409, "leftovers_supplies_others" if exc.reason == "supplies_others" else "leftovers_not_leftover", exc) from exc
    except (sqlite3.Error, OSError) as exc:
        raise api_error(503, "leftovers_unavailable", exc) from exc
    return {"forgotten": install_id}
