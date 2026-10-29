
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.auth import require_auth
from src.config import settings as app_settings
from src.core.db import connect, db_path_for
from src.core.transcript_manifest import condition, store
from src.core.transcript_manifest import constants as K

router = APIRouter(prefix="/transcripts", tags=["transcripts"], dependencies=[Depends(require_auth)])

_FAMILIES = (K.FAMILY_CLAUDE, K.FAMILY_CODEX)


def _state_dir() -> Path:
    """The install's state directory. Separate function so tests can point it elsewhere."""
    return app_settings.get_state_dir()


def _read(filters: Dict[str, Any], limit: int, offset: int) -> Dict[str, Any]:
    with closing(connect(db_path_for(_state_dir()), create=False)) as conn:
        return {"summary": store.summary(conn), "last_scan": condition.last_scan(),
                "files": store.list_rows(conn, limit=limit, offset=offset, **filters),
                "limit": limit, "offset": offset}


@router.get("/manifest")
async def get_manifest(status: Optional[str] = Query(None), kind: Optional[str] = Query(None),
                       family: Optional[str] = Query(None), conversation_id: Optional[str] = Query(None),
                       limit: int = Query(K.DEFAULT_LIST_LIMIT, ge=1, le=K.MAX_LIST_LIMIT),
                       offset: int = Query(0, ge=0)) -> Dict[str, Any]:
    """The manifest's summary, the last scan and a filtered page of files. Output: see the module docstring.

    Raises: HTTPException 422 on an unknown status, kind or family.
    """
    for name, value, allowed in (("status", status, K.STATUSES), ("kind", kind, K.KINDS), ("family", family, _FAMILIES)):
        if value is not None and value not in allowed:
            raise HTTPException(status_code=422, detail=f"unknown {name}: {value}")
    filters = {"status": status, "kind": kind, "family": family, "conversation_id": conversation_id}
    return await asyncio.to_thread(_read, filters, limit, offset)
