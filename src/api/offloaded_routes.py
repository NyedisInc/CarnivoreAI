
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.core.backup_health import offload_guard

router = APIRouter(tags=["offloaded"], dependencies=[Depends(require_auth)])


class OffloadedOut(BaseModel):
    """What is offloaded for a session or a conversation."""

    code: str = Field(description="always 'offloaded'")
    detail: str
    conversations: List[str] = Field(description="the offloaded conversation ids that matched")
    sessions: List[str]
    bytes: int = Field(description="their size on disk before they left, summed")
    offloaded_at: float = Field(description="epoch seconds the newest of them left; 0 when unknown")
    restore_route: str = Field(description="the plugin's restore route, relative to /api/v1/cplugs/save, with {session_uuid} to fill")
    plugin_on: bool = Field(description="the conversation backups plugin is running now; false means turn backups on to restore")
    unreadable: bool = Field(description="the offloaded list could not be read, so nothing is known about size or date")


@router.get("/offloaded", response_model=OffloadedOut)
async def get_offloaded(session_uuid: Optional[str] = None, conversation_id: Optional[str] = None) -> OffloadedOut:
    """What the restore prompt shows: the offloaded conversations of a session, or one conversation. Read only."""
    if not session_uuid and not conversation_id:
        raise HTTPException(status_code=400, detail="give session_uuid or conversation_id")
    found = await run_in_threadpool(offload_guard.summary, session_uuid or None, conversation_id or None)
    if found is None:
        raise HTTPException(status_code=404, detail="nothing is offloaded for that")
    return OffloadedOut(**found)
