
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.plugins.save.offload import constants as C
from src.plugins.save.offload import restore_chain, target_folder
from src.plugins.save.offload.chain import build
from src.plugins.save.offload.homes import NoProjectsFolder, claude_homes
from src.plugins.save.offload.ledger import OPERATION, Ledger
from src.plugins.save.service import RUNTIME
from src.plugins.save.vault.location import VaultUnavailable
from src.plugins.save.vault.manifest import ManifestError, check_unit
from src.plugins.save.vault.store import Vault
from src.plugins.sdk import session_chains

logger = structlog.get_logger()


class RestoreBody(BaseModel):
    """How to restore."""

    dry_run: bool = Field(False, description="classify every file and report; write nothing")


class ConversationOut(BaseModel):
    """One conversation's restore outcome."""

    conversation_id: str
    status: str = Field(description="written | already_present | disk_newer | conflict | present_elsewhere (already on disk in another project folder; nothing written, see notes) | failed | no_vault_point | would_write (dry run). The counts always say what is on disk NOW, also for conflict and failed")
    point_id: Optional[str] = None
    written: int = 0
    already_present: int = 0
    disk_newer: int = 0
    conflicts: List[str] = Field(default_factory=list, description="destinations holding a different file; nothing of the conversation was written")
    bytes: int = 0
    detail: str = ""
    notes: List[str] = Field(default_factory=list, description="grew_during_restore: <path> when a resumed conversation appended to a file while it was restored (still written); restored_into: <folder> when the conversation went into its session's resume folder instead of the recorded one; present_elsewhere: <path> (<state>) for the copy already on disk elsewhere")
    path: str = Field("", description="what the status is about: the copy found for present_elsewhere, the folder that could not be searched for that failed; '' otherwise")


class RestoreOut(BaseModel):
    """The outcome of a restore: one entry per conversation. No session is ever started."""

    session_uuid: Optional[str] = None
    dry_run: bool
    started_session: bool = Field(False, description="always false: a restore never starts, wakes or resumes a session")
    conversations: List[ConversationOut]


def _vault() -> Vault:
    try:
        return RUNTIME.vault()
    except VaultUnavailable as exc:
        raise HTTPException(status_code=409, detail={"code": "vault_unavailable", "detail": str(exc)})


def _homes() -> Dict[str, Path]:
    try:
        return claude_homes(RUNTIME.sources().claude_roots)
    except NoProjectsFolder as exc:
        raise HTTPException(status_code=409, detail={"code": "no_projects_folder", "detail": str(exc)})


def _snapshot() -> session_chains.ChainSnapshot:
    try:
        return session_chains.read_snapshot()
    except session_chains.SessionChainsUnreadable as exc:
        raise HTTPException(status_code=503, detail={"code": "sessions_unreadable", "detail": str(exc)})


def run_restore(session_uuid: Optional[str], conversation_id: Optional[str], dry_run: bool) -> RestoreOut:
    snapshot = _snapshot()
    if session_uuid is not None:
        chains = build(snapshot).chains
        if session_uuid not in chains:
            raise HTTPException(status_code=404, detail=f"no session {session_uuid}")
        ids: List[str] = list(chains[session_uuid])
    else:
        try:
            ids = [check_unit(conversation_id or "")]
        except ManifestError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    vault = _vault()
    homes = _homes()
    safe = [i for i in ids if _safe(i)]
    folders = target_folder.resume_folders(snapshot, safe)
    ledger = Ledger(vault.root, RUNTIME.sources().state_dir)
    if dry_run:
        outcomes = restore_chain.restore_conversations(vault, safe, homes, dry_run=True, ledger=ledger, folders=folders)
    else:
        if not OPERATION.acquire(blocking=False):
            raise HTTPException(status_code=409, detail={"code": C.CODE_BUSY, "detail": "another offload or restore is running; try again when it has finished"})
        try:
            outcomes = restore_chain.restore_conversations(vault, safe, homes, ledger=ledger, folders=folders)
        finally:
            OPERATION.release()
    return RestoreOut(session_uuid=session_uuid, dry_run=dry_run, conversations=[ConversationOut(**vars(o)) for o in outcomes])


def _safe(conversation_id: str) -> bool:
    try:
        check_unit(conversation_id)
        return True
    except ManifestError:
        logger.warning("offload_restore_unsafe_id", conversation_id=conversation_id)
        return False


def add_to(router: APIRouter) -> None:

    @router.post("/offload/sessions/{session_uuid}/restore", response_model=RestoreOut)
    async def restore_session(session_uuid: str, body: Optional[RestoreBody] = None) -> RestoreOut:
        """Put back every conversation of this session's chain that is missing, from the vault. Never overwrites, never starts a session."""
        return await run_in_threadpool(run_restore, session_uuid, None, bool(body and body.dry_run))

    @router.post("/offload/conversations/{conversation_id}/restore", response_model=RestoreOut)
    async def restore_conversation(conversation_id: str, body: Optional[RestoreBody] = None) -> RestoreOut:
        """Put back one conversation from the vault. Never overwrites, never starts a session."""
        return await run_in_threadpool(run_restore, None, conversation_id, bool(body and body.dry_run))
