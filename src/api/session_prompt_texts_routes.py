
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.core.session_conversations.prompt_texts import read_prompt_texts

router = APIRouter(tags=["session-prompt-texts"], dependencies=[Depends(require_auth)])


class PromptTexts(BaseModel):
    """The newest typed prompts of one session, oldest first."""

    prompts: List[str] = Field(default_factory=list)


@router.get("/sessions/{session_id}/prompt-texts", response_model=PromptTexts)
async def get_prompt_texts(request: Request, session_id: str) -> PromptTexts:
    """The session's typed prompts from its transcript; empty for a non-claude or unreadable one.

    Example: GET /api/v1/sessions/ses_1/prompt-texts -> {"prompts": ["fix it\\n\\nand test"]}
    """
    info = await request.app.state.session_manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="unknown session")
    if info.agent_family != "claude":
        return PromptTexts()
    texts = await run_in_threadpool(
        read_prompt_texts, info.claude_session_uuid, info.session.working_dir)
    return PromptTexts(prompts=texts)
