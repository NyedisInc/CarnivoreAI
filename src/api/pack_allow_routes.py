
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from src.api import projects_service
from src.api.auth import require_auth
from src.config import settings
from src.core.pack.identity import home

router = APIRouter(prefix="/pack", tags=["pack-machines"], dependencies=[Depends(require_auth)])


def _read_choices() -> Dict[str, Any]:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        projects = conn.execute(
            "SELECT p.uid AS uid, p.display_name AS name, c.uid AS company_uid FROM projects p "
            "LEFT JOIN companies c ON c.id = p.company_id "
            "WHERE p.archived_at IS NULL AND p.uid IS NOT NULL AND COALESCE(p.pack_state, ?) != ? "
            "ORDER BY p.display_name COLLATE NOCASE, p.uid", (home.HOME, home.MOVED_AWAY)).fetchall()
        companies = conn.execute("SELECT uid, name FROM companies WHERE uid IS NOT NULL ORDER BY name COLLATE NOCASE, uid").fetchall()
    return {"projects": [dict(r) for r in projects], "companies": [dict(r) for r in companies]}


@router.get("/allow-choices")
async def allow_choices() -> Dict[str, Any]:
    """GET /pack/allow-choices: the projects and companies the allow lists may name. Output: see :func:`_read_choices`."""
    return await run_in_threadpool(_read_choices)
