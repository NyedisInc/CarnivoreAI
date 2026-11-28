
from __future__ import annotations

import asyncio
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from src.api.agent_auth import require_agent
from src.core.perf_hooks import executors
from src.core.mcp.caller import AgentCaller
from src.core.pack.jobs import boot, precheck
from src.core.pack.jobs.types import JobError
from src.core.pack.placement import explain

router = APIRouter(tags=["pack-jobs"])


def _answer(verdict: precheck.Verdict) -> Dict[str, Any]:
    out: Dict[str, Any] = {"decision": verdict.decision, "computer": verdict.computer, "reason": verdict.reason}
    note = explain.mesh_note()
    if note is not None:
        out["note"] = note
    return out


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
    verdict = await executors.run_in(executors.precheck_executor(), precheck.decide, engine, caller.tmux_name, body.command, body.folder,
                                     tool_use_id=body.tool_use_id, background=body.background, timeout_ms=body.timeout_ms)
    return _answer(verdict)


class AgentPrecheckBody(BaseModel):
    """A subagent about to start and where (Claude Code or agy). Example: {"folder": "/Users/a/app", "family": "agy"}."""

    model_config = ConfigDict(extra="forbid")
    folder: str = Field(min_length=1, max_length=4096)
    family: Optional[Literal["claude", "codex", "agy"]] = None


@router.post("/pack/jobs/precheck/agent")
async def post_precheck_agent(body: AgentPrecheckBody, caller: AgentCaller = Depends(require_agent)) -> Dict[str, Any]:
    """Should this subagent run here? Inputs: body; caller (the pane, from its token). Output: ``{decision, computer, reason}``, ``run`` on any doubt."""
    if caller.external:
        return {"decision": "run"}
    try:
        engine = boot.engine()
    except JobError:
        return {"decision": "run"}
    verdict = await executors.run_in(executors.precheck_executor(), precheck.decide_agent, engine, caller.tmux_name, body.folder, family=body.family)
    return _answer(verdict)


@router.post("/pack/jobs/precheck/finished")
async def post_precheck_finished(body: FinishedBody, caller: AgentCaller = Depends(require_agent)) -> Dict[str, Any]:
    """A command finished: record its wall time under its shape (``precheck_learn``). Inputs: body; caller. Output: ``{"ok": true}`` always (best effort)."""
    if not caller.external:
        try:
            engine = boot.engine()
        except JobError:
            return {"ok": True}
        await executors.run_in(executors.precheck_executor(), precheck.finished, engine, caller.tmux_name, body.tool_use_id)
    return {"ok": True}
