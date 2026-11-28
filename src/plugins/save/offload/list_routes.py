
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.plugins.save.offload import batch_routes, constants as C, list_view, restore_batch_routes, settings
from src.plugins.save.offload.ledger import Ledger, LedgerUnreadable
from src.plugins.save.service import RUNTIME
from src.plugins.save.vault.location import VaultUnavailable
from src.plugins.sdk import session_chains, vault_sources

logger = structlog.get_logger()


class RowOut(BaseModel):
    """One row of the offloaded list."""

    kind: str = Field(description="session | conversation (a conversation no session holds)")
    session_uuid: Optional[str] = None
    conversation_id: Optional[str] = Field(None, description="set for kind conversation only")
    title: Optional[str] = None
    project_id: Optional[int] = None
    project: Optional[str] = None
    conversations: int
    bytes: int
    offloaded_at: float = Field(description="epoch seconds the newest of its conversations left")
    state: str = Field(description="the worst of its conversations: failed | conflict | restoring | offloading | offloaded")
    error: str = Field("", description="why, for a conflict or failed row")
    error_code: str = Field("", description="the restore status behind that reason (present_elsewhere, conflict, failed, ...); '' when none was recorded")
    error_path: str = Field("", description="the file or folder the reason names: the copy found elsewhere, the folder that could not be read, the file in the way")


class TotalsOut(BaseModel):
    """Distinct conversations over the whole filtered set."""

    rows: int
    conversations: int
    bytes: int


class OffloadedOut(BaseModel):
    """A page of the offloaded list."""

    enabled: bool = Field(description="the offload setting: false means the offload route refuses; the list and restore work either way")
    totals: TotalsOut
    rows: List[RowOut]
    next_cursor: Optional[str] = None
    batch: Optional[batch_routes.BatchOut] = Field(None, description="the newest staged bulk offload of this run of the app (running or last run), so the page shows its progress on the same push")
    restore_batch: Optional[restore_batch_routes.RestoreBatchOut] = Field(None, description="the newest bulk restore of this run of the app (running or last run), so the page shows its progress on the same push (#2868)")


def _names() -> Tuple[Dict[str, Tuple[Optional[str], Optional[int]]], Dict[int, str]]:
    names: Dict[str, Tuple[Optional[str], Optional[int]]] = {}
    projects: Dict[int, str] = {}
    try:
        names = {f.session_uuid: (f.title, f.project_id) for f in session_chains.read_snapshot().sessions}
    except session_chains.SessionChainsUnreadable as exc:
        logger.warning("offload_list_names_unreadable", error=str(exc)[:200])
    try:
        projects = vault_sources.project_names(RUNTIME.sources().state_dir)
    except vault_sources.SourceUnavailable as exc:
        logger.warning("offload_list_projects_unreadable", error=str(exc)[:200])
    return names, projects


def list_page(state: Optional[str], cursor: Optional[str], limit: int) -> OffloadedOut:
    if state is not None and state not in C.STATES:
        raise HTTPException(status_code=400, detail=f"state is one of {', '.join(C.STATES)}")
    if not 1 <= limit <= C.PAGE_MAX:
        raise HTTPException(status_code=400, detail=f"limit is a whole number from 1 to {C.PAGE_MAX}")
    try:
        vault = RUNTIME.vault()
    except VaultUnavailable as exc:
        raise HTTPException(status_code=409, detail={"code": "vault_unavailable", "detail": str(exc)})
    try:
        entries = Ledger(vault.root, RUNTIME.sources().state_dir).read().values()
    except LedgerUnreadable as exc:
        raise HTTPException(status_code=503, detail={"code": C.CODE_LEDGER_UNREADABLE, "detail": str(exc)})
    names, projects = _names()
    rows, totals = list_view.group_rows(entries, names, projects, state)
    try:
        page = list_view.page_of(rows, totals, cursor, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return OffloadedOut(enabled=settings.is_enabled(RUNTIME.sources().state_dir), totals=TotalsOut(**vars(page.totals)), rows=[RowOut(**vars(r)) for r in page.rows], next_cursor=page.next_cursor,
                       batch=batch_routes.latest_out(), restore_batch=restore_batch_routes.latest_out())


def add_to(router: APIRouter) -> None:

    @router.get("/offload", response_model=OffloadedOut)
    async def get_offloaded(state: Optional[str] = Query(None, max_length=16), limit: int = Query(C.PAGE_DEFAULT, ge=1, le=C.PAGE_MAX),
                            cursor: Optional[str] = Query(None, max_length=16)) -> OffloadedOut:
        """What is offloaded, one row per session, newest first, with the offload setting. Read only; works while the offload is switched off."""
        return await run_in_threadpool(list_page, state, cursor, limit)
