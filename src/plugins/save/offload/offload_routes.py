
from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.plugins.save.offload import run, settings
from src.plugins.save.offload.homes import NoProjectsFolder, claude_homes
from src.plugins.save.offload.ledger import Ledger
from src.plugins.save.offload.move import holding_root
from src.plugins.save.offload.routes import open_install
from src.plugins.save.service import RUNTIME
from src.plugins.save.vault.units import Scanner
from src.plugins.sdk import session_chains

logger = structlog.get_logger()


class OffloadBody(BaseModel):
    """How to offload."""

    dry_run: bool = Field(False, description="eligibility only: report what would go, change nothing")


class OffloadedConversationOut(BaseModel):
    """One conversation of the chain."""

    conversation_id: str
    status: str = Field(description="offloaded | would_offload (dry run)")
    point_id: Optional[str] = Field(None, description="the vault point it was verified against")
    files: int
    bytes: int
    holding_dir: str = Field("", description="where its files are held (empty in a dry run)")


class OffloadOut(BaseModel):
    """The outcome of an offload."""

    session_uuid: str
    dry_run: bool
    bytes: int
    conversations: List[OffloadedConversationOut]
    already_offloaded: List[str] = Field(description="chain conversations an earlier offload already holds (now also this session's)")


def _run(session_uuid: str, dry_run: bool) -> OffloadOut:
    evaluator, ready = open_install()
    vault = RUNTIME.vault()
    sources = RUNTIME.sources()
    try:
        homes = claude_homes(sources.claude_roots)
    except NoProjectsFolder as exc:
        raise HTTPException(status_code=409, detail={"code": "no_projects_folder", "detail": str(exc)})
    try:
        result = run.offload_session(session_uuid, evaluator=evaluator, ready=ready, vault=vault, scanner=Scanner(sources), ledger=Ledger(vault.root, sources.state_dir),
                                     holding_root=holding_root(sources.state_dir), running_now=session_chains.read_running, homes=homes, dry_run=dry_run)
    except run.UnknownSession:
        raise HTTPException(status_code=404, detail=f"no session {session_uuid}")
    except run.OffloadRefused as exc:
        logger.warning("offload_refused", session_uuid=session_uuid, code=exc.code, reasons=list(exc.reasons))
        raise HTTPException(status_code=409, detail={"code": exc.code, "detail": exc.detail, "reasons": list(exc.reasons), "stuck": list(exc.stuck)})
    return OffloadOut(session_uuid=result.session_uuid, dry_run=result.dry_run, bytes=result.bytes, already_offloaded=result.already_offloaded,
                      conversations=[OffloadedConversationOut(**vars(c)) for c in result.conversations])


def _run_if_enabled(session_uuid: str, dry_run: bool) -> OffloadOut:
    settings.require_enabled(RUNTIME.sources().state_dir)
    return _run(session_uuid, dry_run)


def add_to(router: APIRouter) -> None:

    @router.post("/offload/sessions/{session_uuid}", response_model=OffloadOut)
    async def offload_session(session_uuid: str, body: Optional[OffloadBody] = None) -> OffloadOut:
        """Move this closed session's whole chain of conversations into holding, after verifying each file against the vault. Never deletes; restore puts them back.

        409 ``offload_disabled`` while the offload setting is off (the default); restore and the list never read it.
        """
        return await run_in_threadpool(_run_if_enabled, session_uuid, bool(body and body.dry_run))
