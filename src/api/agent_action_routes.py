
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.error_response import api_error
from src.api.auth import require_auth
from src.config import settings
from src.core import config_writer
from src.core.mcp import pending
from src.core.mcp.approvals import typed_confirm
from src.core.mcp.write_tools import gate_enabled

logger = structlog.get_logger()
router = APIRouter(prefix="/agent-actions", tags=["agent-actions"], dependencies=[Depends(require_auth)])


class ApproveBody(BaseModel):
    """The owner's answer on an approval that asks a hard question: the exact words he typed (``typed``)."""

    typed: Optional[str] = Field(default=None, max_length=1000)


class GateSetting(BaseModel):
    """``mcp.gate_cross_session_actions``: True holds cross-session agent actions for approval."""

    gate_cross_session_actions: bool


@router.get("")
async def list_agent_actions() -> dict:
    """Pending agent actions, oldest first, plus the store's change counter.

    Output: {"items": [...], "version": int}.
    """
    store = pending.get_store()
    return {"items": store.list(), "history": store.decided(), "version": store.version}


@router.get("/settings", response_model=GateSetting)
async def get_gate_setting() -> GateSetting:
    """Whether the cross-session gate is on (default off; an unreadable config fails closed). Output: GateSetting."""
    return GateSetting(gate_cross_session_actions=gate_enabled())


@router.put("/settings", response_model=GateSetting)
async def put_gate_setting(body: GateSetting) -> GateSetting:
    """Turn the cross-session gate on or off.

    Inputs: body (GateSetting). Output: GateSetting as written.
    Raises: HTTPException 500 when config.json is missing or unwritable.
    """
    def mutate(doc: dict) -> dict:
        block = doc.get("mcp")
        block = dict(block) if isinstance(block, dict) else {}
        block["gate_cross_session_actions"] = body.gate_cross_session_actions
        return {**doc, "mcp": block}

    try:
        await asyncio.to_thread(
            config_writer.commit, Path(settings.auth_config_file).expanduser(), mutate
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.error("mcp_gate_setting_unwritable", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="config.json could not be updated") from exc
    settings.drop_auth_config_cache()
    logger.info("mcp_gate_setting_set", enabled=body.gate_cross_session_actions)
    return body


async def _decide(action_id: str, approve: bool, typed: Optional[str] = None) -> dict:
    store = pending.get_store()
    try:
        item = await store.approve(action_id, typed=typed) if approve else store.deny(action_id)
    except typed_confirm.ConfirmationMismatch as exc:
        raise api_error(422, "typed_confirmation_mismatch", exc, action=action_id) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail="no such pending agent action")
    except ValueError as exc:
        raise api_error(409, "agent_action_not_pending", exc, action=action_id) from exc
    logger.info("agent_action_decided", id=action_id, action=item.action, status=item.status)
    return {**item.as_dict(), "result": item.result}


@router.post("/{action_id}/approve")
async def approve_agent_action(action_id: str, body: Optional[ApproveBody] = None) -> dict:
    """Run the action with its original args. Output: the item plus the tool ``result``.

    Inputs: action_id; body (optional) - ``typed``, the owner's answer when the card asks a hard question
      (``confirm_text`` on the item, ``approvals/typed_confirm.py``).
    """
    return await _decide(action_id, True, body.typed if body is not None else None)


@router.post("/{action_id}/deny")
async def deny_agent_action(action_id: str) -> dict:
    """Refuse the action; the waiting agent gets a tool error. Output: the item."""
    return await _decide(action_id, False)
