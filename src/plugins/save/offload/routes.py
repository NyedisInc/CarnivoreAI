
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.plugins.save.offload import constants as C
from src.plugins.save.offload import report
from src.plugins.save.offload.move import holding_root
from src.plugins.save.offload.eligibility import ConversationVerdict, Evaluator, SessionVerdict
from src.plugins.save.service import RUNTIME
from src.plugins.save.vault.location import VaultUnavailable
from src.plugins.save.vault.units import Scanner
from src.plugins.sdk import session_chains

logger = structlog.get_logger()


class ReadinessOut(BaseModel):
    """Whether an offload may start at all."""

    ready: bool
    blockers: List[str] = Field(description="icloud_path | icloud_unknown | registry_unreadable; nothing may be offloaded while one stands")


class TotalsOut(BaseModel):
    """Distinct conversations and their bytes (on disk, before compression)."""

    sessions: int
    conversations: int
    bytes: int


class ConversationOut(BaseModel):
    """One conversation's verdict."""

    conversation_id: str
    on_disk: bool = Field(description="false: nothing of it is under the live projects folder, so there is nothing to move")
    eligible: bool
    reasons: List[str] = Field(description="live | asleep | remote | unknown_state | in_use | not_quiet | dataless | no_vault_point | vault_behind | unreadable_file | not_ready")
    bytes: int
    files: int
    point_id: Optional[str] = Field(None, description="the vault's newest point of it")
    owners: List[str] = Field(description="every session whose chain holds it")
    shared: bool = Field(description="held by more than one session")


class SessionOut(BaseModel):
    """One session's chain and verdict."""

    session_uuid: str
    title: Optional[str] = None
    project_id: Optional[int] = None
    offloadable: bool
    reasons: List[str] = Field(description="the union of its conversations' reasons, or nothing_on_disk")
    bytes: int
    idle_days: Optional[float] = None
    shared: bool
    conversations: List[ConversationOut]
    readiness: ReadinessOut


class CandidateOut(BaseModel):
    """One offloadable session in the list (the detail route has its conversations)."""

    session_uuid: str
    title: Optional[str] = None
    project_id: Optional[int] = None
    conversations: int
    bytes: int
    idle_days: Optional[float] = None
    shared: bool


class CandidatesOut(BaseModel):
    """The dry-run: a page of offloadable sessions and the summary of the whole set."""

    readiness: ReadinessOut
    idle_days: int
    offloadable: TotalsOut = Field(description="sessions idle idle_days or more that could go now; conversations counted once")
    offloadable_any_idle: TotalsOut = Field(description="the same without the idle filter")
    no_session: TotalsOut = Field(description="conversations no session holds that could go now (a later batch)")
    blocked: Dict[str, int] = Field(description="sessions blocked, by reason (a session with two reasons counts under both)")
    total: int
    candidates: List[CandidateOut]
    next_cursor: Optional[str] = None


def _conversation_out(v: ConversationVerdict) -> ConversationOut:
    return ConversationOut(conversation_id=v.conversation_id, on_disk=v.on_disk, eligible=v.eligible, reasons=list(v.reasons), bytes=v.bytes,
                           files=v.files, point_id=v.point_id, owners=list(v.owners), shared=len(v.owners) > 1)


def open_install() -> Tuple[Evaluator, report.Readiness]:
    try:
        snapshot = session_chains.read_snapshot()
    except session_chains.SessionChainsUnreadable as exc:
        raise HTTPException(status_code=503, detail={"code": "sessions_unreadable", "detail": str(exc)})
    try:
        vault = RUNTIME.vault()
    except VaultUnavailable as exc:
        raise HTTPException(status_code=409, detail={"code": "vault_unavailable", "detail": str(exc)})
    running = session_chains.read_running()
    sources = RUNTIME.sources()
    ready = report.readiness(sources.claude_roots, running, holding_root(sources.state_dir))
    return Evaluator(snapshot, running, Scanner(sources), vault, time.time(), blockers=ready.blockers), ready


def _candidates(idle_days: int, cursor: Optional[str], limit: int) -> CandidatesOut:
    evaluator, ready = open_install()
    try:
        page = report.build_page(evaluator, ready, idle_days, cursor, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rows = [CandidateOut(session_uuid=v.session_uuid, title=v.title, project_id=v.project_id, conversations=sum(1 for c in v.conversations if c.on_disk),
                         bytes=v.bytes, idle_days=evaluator.idle_days(v.idle_epoch), shared=v.shared) for v in page.candidates]
    return CandidatesOut(readiness=ReadinessOut(ready=ready.ready, blockers=list(ready.blockers)), idle_days=page.idle_days,
                         offloadable=TotalsOut(**vars(page.offloadable)), offloadable_any_idle=TotalsOut(**vars(page.offloadable_any_idle)),
                         no_session=TotalsOut(**vars(page.no_session)), blocked=page.blocked, total=page.total_candidates, candidates=rows,
                         next_cursor=page.next_cursor)


def _session(session_uuid: str) -> SessionOut:
    evaluator, ready = open_install()
    verdict: Optional[SessionVerdict] = evaluator.session(session_uuid)
    if verdict is None:
        raise HTTPException(status_code=404, detail=f"no session {session_uuid}")
    return SessionOut(session_uuid=verdict.session_uuid, title=verdict.title, project_id=verdict.project_id, offloadable=verdict.offloadable,
                      reasons=list(verdict.reasons), bytes=verdict.bytes, idle_days=evaluator.idle_days(verdict.idle_epoch), shared=verdict.shared,
                      conversations=[_conversation_out(c) for c in verdict.conversations],
                      readiness=ReadinessOut(ready=ready.ready, blockers=list(ready.blockers)))


def add_to(router: APIRouter) -> None:

    @router.get("/offload/candidates", response_model=CandidatesOut)
    async def get_candidates(idle_days: int = Query(C.DEFAULT_IDLE_DAYS, ge=0, le=3650), limit: int = Query(C.PAGE_DEFAULT, ge=1, le=C.PAGE_MAX),
                             cursor: Optional[str] = Query(None, max_length=16)) -> CandidatesOut:
        """The sessions that could be offloaded now, with totals and what blocks the rest. Read only."""
        return await run_in_threadpool(_candidates, idle_days, cursor, limit)

    @router.get("/offload/sessions/{session_uuid}", response_model=SessionOut)
    async def get_session(session_uuid: str) -> SessionOut:
        """One session's chain, each conversation's owners and verdict, and the reasons. Read only."""
        return await run_in_threadpool(_session, session_uuid)
