
from __future__ import annotations

from contextlib import closing
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.api.peer_auth import require_peer_sessions
from src.config import settings
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.layouts.lease import SESSION_LEASES
from src.core.session_group_membership_migrate import resolve_session_uuid

router = APIRouter()


def _resolve(name: str):
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        return resolve_session_uuid(conn, name)


@router.put("/sessions/{session_name}/active", dependencies=[Depends(require_peer_sessions)])
async def renew_session_lease(session_name: str) -> Dict[str, int]:
    try:
        session_uuid = await run_in_threadpool(_resolve, session_name)
    except (DatastoreUnreadableError, OSError):
        raise HTTPException(503, {"code": "datastore_unavailable", "message": "the datastore cannot be read"}) from None
    if session_uuid is None:
        raise HTTPException(404, {"code": "session_not_found", "message": "no such session"})
    SESSION_LEASES.renew(session_uuid)
    return {"lease_seconds": int(SESSION_LEASES.lease_seconds)}
