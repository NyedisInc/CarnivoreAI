
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from src.api.agent_auth import require_agent
from src.core.beast_prompts import hook_decision
from src.core.mcp.caller import AgentCaller

router = APIRouter(tags=["beast-mode"])


class PermissionRequestBody(BaseModel):
    """The request claude is about to ask about. Example: {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/work/app"}."""

    model_config = ConfigDict(extra="ignore")
    tool_name: str = Field(min_length=1, max_length=200)
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    cwd: str = Field(default="", max_length=4096)


@router.post("/beast-mode/permission-request")
async def post_permission_request(body: PermissionRequestBody, caller: AgentCaller = Depends(require_agent)) -> Dict[str, str]:
    """Allow this one call? Inputs: body; caller (the pane, from its token). Output: ``{"decision": "allow" | "none"}``.

    ``none`` for an external token, a tool that is always the owner's, Beast off or the row unticked, and any error: the dialog shows.
    """
    if caller.external or not await asyncio.to_thread(hook_decision.allowed, body.tool_name):
        return {"decision": "none"}
    await asyncio.to_thread(hook_decision.record, caller.current_session_id, caller.tmux_name, body.tool_name, body.tool_input)
    return {"decision": "allow"}
