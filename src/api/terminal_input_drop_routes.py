
from __future__ import annotations

import time
from enum import Enum
from typing import Dict, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth

logger = structlog.get_logger()
router = APIRouter(tags=["terminal"], dependencies=[Depends(require_auth)])

EVENT_NAME = "terminal_input_dropped"
PER_KEY_GAP_S = 10.0
GLOBAL_PER_MINUTE = 60
_ID_PATTERN = r"^[A-Za-z0-9:@_.\-/]{0,120}$"


class InputDropReason(str, Enum):

    owner_refused = "owner_refused"
    no_socket = "no_socket"
    held_pre_ready = "held_pre_ready"
    buffer_overflow = "buffer_overflow"
    buffer_poisoned = "buffer_poisoned"
    stale_generation = "stale_generation"
    no_live_pane = "no_live_pane"


class InputDropReport(BaseModel):
    """Body of ``POST /terminal/input-drops``. Unknown fields are a 422."""

    model_config = ConfigDict(extra="forbid")

    reason: InputDropReason
    slot: Optional[str] = Field(default=None, pattern=_ID_PATTERN)
    owner: Optional[str] = Field(default=None, pattern=_ID_PATTERN)
    active_slot: Optional[str] = Field(default=None, pattern=_ID_PATTERN)
    hidden: Optional[bool] = None
    ws_state: Optional[int] = Field(default=None, ge=-1, le=3)
    buffer_phase: Optional[str] = Field(default=None, pattern=r"^[a-z_]{0,40}$")
    layout_id: Optional[str] = Field(default=None, pattern=_ID_PATTERN)
    page_ms: Optional[int] = Field(default=None, ge=0, le=10**10)


_last_logged: Dict[Tuple[str, str], float] = {}
_recent: list = []


def _admit(key: Tuple[str, str], now: float) -> bool:
    last = _last_logged.get(key)
    if last is not None and now - last < PER_KEY_GAP_S:
        return False
    _recent[:] = [t for t in _recent if now - t < 60.0]
    if len(_recent) >= GLOBAL_PER_MINUTE:
        return False
    if len(_last_logged) > 2000:
        _last_logged.clear()
    _last_logged[key] = now
    _recent.append(now)
    return True


@router.post("/terminal/input-drops", status_code=202)
async def report_input_drop(body: InputDropReport) -> Dict[str, bool]:
    """Log one renderer-side input drop as ``terminal_input_dropped``, unless rate limited.

    Input: the report body. Output: ``{"logged": bool}``.
    Example: POST /api/v1/terminal/input-drops {"reason": "owner_refused", "slot": "@primary", "owner": "terminal:row:32"} -> 202 {"logged": true}
    """
    if not _admit((body.slot or "", body.reason.value), time.monotonic()):
        return {"logged": False}
    logger.warning(EVENT_NAME, **body.model_dump(mode="json"))
    return {"logged": True}
