
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.argent.status import feature_on
from src.api.auth import require_auth
from src.core.argent import cost_split, budget, cost_poller, work_items
from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentError, NotFound, Unauthorized, Unreachable

logger = structlog.get_logger()
router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])


class BudgetRequest(BaseModel):
    """Ask for more budget. Example: {"item_id": "wi_story1", "note": "release week"}"""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., min_length=1, max_length=200)
    note: str = Field("", max_length=500)


class BudgetLift(BaseModel):
    """Which item the owner wants to lift in Argent. Example: {"item_id": "wi_story1"}"""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., min_length=1, max_length=200)


class AgentWatch(BaseModel):
    """The session rows one browser window is showing the per-agent split for now ([] = none). Example: {"client_id": "w1", "row_ids": ["7"]}"""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(..., min_length=1, max_length=80)
    row_ids: List[str] = Field(default_factory=list, max_length=50)


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _call(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not feature_on():
        raise _refuse(409, "feature_off", "turn the argent feature on first")
    try:
        client, _tenant = await work_items.client_for_call()
        return dict((await client.post(path, json=payload)).body)
    except Unauthorized as exc:
        raise _refuse(403, "login_required" if exc.code == "login_required" else "login_expired", "log in to argent again") from None
    except NotFound:
        raise _refuse(503, "unavailable", "argent cannot do that yet") from None
    except Unreachable:
        raise _refuse(502, "argent_unreachable", "argent did not answer") from None
    except ArgentError as exc:
        err = exc.body.get("error") if isinstance(exc.body.get("error"), dict) else {}
        raise _refuse(exc.status or 502, exc.code or "argent_refused", str(err.get("message") or "argent refused")) from None


@router.get("/cost")
async def get_cost() -> Dict[str, Any]:
    """The last cost and budget snapshot. Output: {enabled, state (off, pending, ok), as_of, sessions: {row id: {ref, items, cost}}, items: {id: {name, cost, budget, held}}}.

    ``cost`` and ``budget`` are null when not measured, never zero. Example: GET /api/v1/argent/cost
    """
    if not feature_on():
        return {"enabled": False, "state": "off", "as_of": None, "sessions": {}, "items": {}}
    return {"enabled": True, **cost_poller.snapshot()}


@router.put("/cost/agents/watch")
async def watch_agent_cost(body: AgentWatch) -> Dict[str, Any]:
    """Register the rows a window shows the per-agent split for; the poller asks Argent about those alone and a new row is polled at once. Output: {enabled, watching}.

    Registrations expire after ``cost_split.WATCH_TTL`` seconds unless renewed. With the feature off nothing is registered and nothing is polled.
    Example: PUT /api/v1/argent/cost/agents/watch {"client_id": "w1", "row_ids": ["7"]}
    """
    if not feature_on():
        return {"enabled": False, "watching": 0}
    if cost_split.watch(body.client_id, body.row_ids, time.time()):
        cost_poller.poke()
    return {"enabled": True, "watching": len(cost_split.watched_rows(time.time()))}


@router.post("/budget/requests")
async def request_budget(body: BudgetRequest) -> Dict[str, Any]:
    """Ask the budget owner for more budget on an item. Output: Argent's answer. Example: POST /api/v1/argent/budget/requests {"item_id": "wi_story1"}"""
    reply = await _call("/v1/my/budget/requests", {"work_item_id": body.item_id, "note": body.note})
    cost_poller.poke()
    return reply


@router.post("/budget/lift")
async def lift_budget(body: BudgetLift) -> Dict[str, Any]:
    """Where the budget owner lifts a hold: Argent's own page. Output: {lift_in_argent: true, url: the NOC work items register with that item open, or null while the server is unknown}.

    Raise and overage are browser-session only on Argent's side (a CLI token is refused, and a 401 would mark the login expired), so this route makes NO call
    to Argent. Example: POST /api/v1/argent/budget/lift {"item_id": "wi_story1"}
    """
    if not feature_on():
        raise _refuse(409, "feature_off", "turn the argent feature on first")
    cfg = await asyncio.to_thread(settings_module.read)
    return {"lift_in_argent": True, "url": budget.noc_budget_url(cfg.server_url, body.item_id)}
