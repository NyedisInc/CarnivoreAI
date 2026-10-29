
from fastapi import APIRouter, Depends
from src.api.auth import require_auth
from src.config import settings
from typing import List

from fastapi.concurrency import run_in_threadpool

router = APIRouter()


@router.get("/projects/presence", dependencies=[Depends(require_auth)])
async def get_projects_presence() -> dict:
    """Live-probe every DB-tracked project's filesystem presence.

    feat/projects-table (S3), design section 4.1. Re-stats every
    ``projects`` row's root right now - the stored ``presence`` column
    is a cache and this endpoint never trusts it stale - and reports one
    of four named states per row: ``present``, ``missing``,
    ``unreachable`` or ``unchecked``. ``missing`` and ``unreachable`` are
    never collapsed into each other: a project behind a permission wall
    or on a sleeping external volume reports ``unreachable`` with its
    errno named in ``presence_detail``, never ``missing``. This route
    only READS the shadow table; config.json is not touched here and
    stays authoritative for writes (see src/core/project_store.py).

    Returns:
        dict - ``{"status": "ok" | "unreachable", "projects": [...],
        "detail": str | None}``. ``status: "unreachable"`` means
        cloude.db itself could not be opened for this request at all -
        a distinct, database-level outcome from any individual
        project's own presence value.
    """
    from contextlib import closing


    from src.core import project_store
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    def _open_probe_and_close() -> List[dict]:
        with closing(connect(db_path, create=False)) as conn:
            return project_store.refresh_and_list_presence(conn)

    db_path = db_path_for(settings.get_state_dir())
    try:
        rows = await run_in_threadpool(_open_probe_and_close)
    except DatastoreUnreadableError as exc:
        return {"status": "unreachable", "projects": [], "detail": str(exc)}

    return {"status": "ok", "projects": rows, "detail": None}
