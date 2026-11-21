
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from src.api.agent_auth import require_agent
from src.core.mcp.caller import AgentCaller
from src.core.pack.jobs import boot, precheck
from src.core.pack.jobs.types import JobError

router = APIRouter(tags=["pack-jobs"])


class PrecheckBody(BaseModel):
    """The command about to run and where. Example: {"command": "pytest -q", "folder": "/Users/a/app"}."""

    model_config = ConfigDict(extra="forbid")
    command: str = Field(min_length=1, max_length=8000)
    folder: str = Field(min_length=1, max_length=4096)
    tool_use_id: str = Field(default="", max_length=200)
    background: bool = False
    timeout_ms: Optional[int] = Field(default=None, ge=0, le=100_000_000_000)


class FinishedBody(BaseModel):
    """A command the pre-run check saw start has finished. Example: {"tool_use_id": "toolu_01"}."""

    model_config = ConfigDict(extra="forbid")
    tool_use_id: str = Field(min_length=1, max_length=200)


@router.post("/pack/jobs/precheck")
async def post_precheck(body: PrecheckBody, caller: AgentCaller = Depends(require_agent)) -> Dict[str, Any]:
    """Should this command run here? Inputs: body; caller (the pane, from its token). Output: ``{decision, computer, reason}``.

    ``run`` for an external token, an unmarked project, no engine yet or any error: the check fails open.
    """
    if caller.external:
        return {"decision": "run"}
    try:
        engine = boot.engine()
    except JobError:
        return {"decision": "run"}
    verdict = await asyncio.to_thread(precheck.decide, engine, caller.tmux_name, body.command, body.folder,
                                    tool_use_id=body.tool_use_id, background=body.background, timeout_ms=body.timeout_ms)
    return {"decision": verdict.decision, "computer": verdict.computer, "reason": verdict.reason}


class AgentPrecheckBody(BaseModel):
    """A Claude Code subagent about to start and where. Example: {"folder": "/Users/a/app"}."""

    model_config = ConfigDict(extra="forbid")
    folder: str = Field(min_length=1, max_length=4096)


@router.post("/pack/jobs/precheck/agent")
async def post_precheck_agent(body: AgentPrecheckBody, caller: AgentCaller = Depends(require_agent)) -> Dict[str, Any]:
    """Should this subagent run here? Inputs: body; caller (the pane, from its token). Output: ``{decision, computer, reason}``, ``run`` on any doubt."""
    if caller.external:
        return {"decision": "run"}
    try:
        engine = boot.engine()
    except JobError:
        return {"decision": "run"}
    verdict = await asyncio.to_thread(precheck.decide_agent, engine, caller.tmux_name, body.folder)
    return {"decision": verdict.decision, "computer": verdict.computer, "reason": verdict.reason}


@router.post("/pack/jobs/precheck/finished")
async def post_precheck_finished(body: FinishedBody, caller: AgentCaller = Depends(require_agent)) -> Dict[str, Any]:
    """A command finished: record its wall time under its shape (``precheck_learn``). Inputs: body; caller. Output: ``{"ok": true}`` always (best effort)."""
    if not caller.external:
        try:
            engine = boot.engine()
        except JobError:
            return {"ok": True}
        await asyncio.to_thread(precheck.finished, engine, caller.tmux_name, body.tool_use_id)
    return {"ok": True}
