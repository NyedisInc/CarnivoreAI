
from __future__ import annotations

import asyncio
from typing import Dict, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_auth
from src.config import settings
from src.core.approvals import beast_policy
from src.core.mcp import beast_mode, beast_store
from src.api.error_response import api_error

logger = structlog.get_logger()
router = APIRouter(prefix="/beast-mode", tags=["beast-mode"], dependencies=[Depends(require_auth)])


class BeastSetting(BaseModel):
    """The owner's desired armed state.

    ``prompts``: also answer session permission prompts (the second scope, Joe (ccsliinc), 2026-10-07).
    ``hours``: auto-off for both scopes, 1, 4 or 8; None is "until I turn it off". Both are ignored on a disarm.
    Example: {"enabled": true, "prompts": true, "hours": 4}
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    prompts: bool = False
    hours: Optional[Literal[1, 4, 8]] = None


class BeastGridUpdate(BaseModel):
    """The boxes to change and/or the folder scope; whatever is absent is left alone.

    ``cells``: ``{cell key: bool}``, every key one of ``beast_grid.cell_defaults`` (``folderTrustOff``, ``agentWritesOn``, ...).
    ``trust_scope``: ``projects`` or ``every``.
    Example: {"cells": {"agentWritesOff": true}, "trust_scope": "projects"}
    """

    model_config = ConfigDict(extra="forbid")

    cells: Optional[Dict[str, bool]] = None
    trust_scope: Optional[Literal["projects", "every"]] = None


@router.get("")
async def get_beast_mode() -> dict:
    """Return armed state, both scopes, arm and auto-off times and the current eligible pending count.

    Output: {enabled, prompts, since, until, pending_count, auto_off_rows}; ``prompts`` is true only while armed;
      ``auto_off_rows`` names the grid rows that auto-approve with Beast DISARMED (``beast_grid.UNCONFIRMED_ROWS`` ticked under "beast off";
      the quiet bolt). An expired auto-off reads as disarmed even before the stored switch is written off.
    Example: GET /api/v1/beast-mode -> {"enabled": true, "prompts": true, "since": "...", "until": null, "pending_count": 0,
      "auto_off_rows": []}
    """
    auto_off_rows = beast_mode.off_column_rows()
    try:
        config = settings.load_auth_config().mcp
        enabled = beast_mode.beast_enabled()
        return {"enabled": enabled, "prompts": enabled and bool(config.beast_prompts),
                "since": config.beast_mode_since if enabled else None,
                "until": config.beast_mode_until if enabled else None,
                "pending_count": beast_mode.pending_count(), "auto_off_rows": auto_off_rows}
    except (ValueError, OSError) as exc:
        logger.warning("beast_mode_status_unreadable", error_type=type(exc).__name__)
        return {"enabled": False, "prompts": False, "since": None, "until": None,
                "pending_count": beast_mode.pending_count(), "auto_off_rows": auto_off_rows}


@router.get("/rules")
async def get_beast_rules() -> dict:
    """The grid as it stands now. Output: {rows, cells, trust_scope, trust_scopes, always_asks, never_answered_screens}.

    Example: GET /api/v1/beast-mode/rules -> {"rows": [{"id": "folder_trust", "kind": "startup", "off": true, "on": true, "mode": "off",
      "handled_now": true, "risk": "medium"}, ...], "cells": {"folderTrustOff": {"value": true, "default": true}, ...}, "trust_scope": "projects", ...}
    """
    return beast_policy.current().status()


@router.put("/rules")
async def put_beast_rules(body: BeastGridUpdate) -> dict:
    """Tick or untick grid boxes and/or choose the folder scope, then answer the grid as it stands.

    Raises: HTTPException 422 - a key that is no box; 500 - config.json unwritable.
    Example: PUT /api/v1/beast-mode/rules {"cells": {"agentWritesOff": true}} -> the same body as GET /rules
    """
    try:
        await asyncio.to_thread(beast_store.write_grid, cells=body.cells, trust_scope=body.trust_scope)
    except ValueError as exc:
        raise api_error(422, "invalid_request", exc, step="put_beast_rules") from exc
    except (FileNotFoundError, OSError) as exc:
        logger.error("beast_grid_unwritable", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="config.json could not be updated") from exc
    logger.info("beast_grid_changed", cells=sorted((body.cells or {}).keys()), trust_scope=body.trust_scope)
    return await get_beast_rules()


@router.put("")
async def put_beast_mode(body: BeastSetting) -> dict:
    """Persist a toggle and auto-approve eligible pending actions when arming.

    Raises: HTTPException 500 - config.json unwritable.
    """
    return await set_beast_mode(body, "route")


async def set_beast_mode(body: BeastSetting, source: str) -> dict:
    async with beast_mode.toggle_lock:
        await _persist_beast_mode(body)
    approved = await beast_mode.approve_pending() if body.enabled else 0
    current = await get_beast_mode()
    logger.info("beast_mode_changed", enabled=current["enabled"], prompts=current["prompts"],
                until=current["until"], pending_approved=approved, source=source)
    return {**current, "approved_count": approved}


async def _persist_beast_mode(body: BeastSetting) -> None:
    try:
        await beast_store.persist(enabled=body.enabled, prompts=body.prompts, hours=body.hours)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.error("beast_mode_setting_unwritable", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="config.json could not be updated") from exc
