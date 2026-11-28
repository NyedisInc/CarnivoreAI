
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.argent.status import feature_on
from src.api.auth import require_auth
from src.core.argent import cost_split, budget, budget_requests, cost_poller, work_items
from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentError, NotFound, Unauthorized, Unreachable
from src.core.argent.runtime import get_runtime

logger = structlog.get_logger()
router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])


class BudgetRequest(BaseModel):
    """Ask for more budget on an item. ``amount_micros`` is the EXTRA amount Argent adds to the asker's current allotment on approval, not a new cap, in whole millionths of a dollar (above zero, at most ``budget_requests.MAX_REQUEST_MICROS``); ``reason`` is trimmed, 1 to 500 characters.

    Example: {"item_id": "wi_story1", "amount_micros": 5000000, "reason": "release week"}
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item_id: str = Field(..., min_length=1, max_length=200)
    amount_micros: int = Field(..., gt=0, le=budget_requests.MAX_REQUEST_MICROS, strict=True)
    reason: str = Field(..., min_length=1, max_length=500)


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


BUDGET_REQUEST_UNAVAILABLE = "asking for more budget is not available yet; ask the budget owner in argent"


async def _call(path: str, payload: Dict[str, Any], *, budget_ask: bool = False) -> Dict[str, Any]:
    return (await _post(path, payload, budget_ask=budget_ask))[0]


async def _post(path: str, payload: Dict[str, Any], *, budget_ask: bool = False) -> Tuple[Dict[str, Any], str]:
    if not feature_on():
        raise _refuse(409, "feature_off", "turn the argent feature on first")
    try:
        client, tenant = await work_items.client_for_call()
        return dict((await client.post(path, json=payload, route_refusal_on_401=budget_ask)).body), tenant
    except Unauthorized as exc:
        if budget_ask and exc.code != "login_required":
            raise _refuse(501, "budget_request_unavailable", BUDGET_REQUEST_UNAVAILABLE) from None
        raise _refuse(403, "login_required" if exc.code == "login_required" else "login_expired", "log in to argent again") from None
    except NotFound:
        if budget_ask:
            raise _refuse(501, "budget_request_unavailable", BUDGET_REQUEST_UNAVAILABLE) from None
        raise _refuse(503, "unavailable", "argent cannot do that yet") from None
    except Unreachable:
        raise _refuse(502, "argent_unreachable", "argent did not answer") from None
    except ArgentError as exc:
        if budget_ask:
            if exc.status in (400, 403):
                raise _refuse(501, "budget_request_unavailable", BUDGET_REQUEST_UNAVAILABLE) from None
            if exc.status == 409 and exc.code == "pending_exists":
                raise _pending(exc.body.get("id")) from None
            raise _refuse(exc.status or 502, "argent_refused", "argent refused the request") from None
        err = exc.body.get("error") if isinstance(exc.body.get("error"), dict) else {}
        raise _refuse(exc.status or 502, exc.code or "argent_refused", str(err.get("message") or "argent refused")) from None


def _pending(request_id: Any) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "budget_request_pending", "message": "already asked; waiting on the budget owner",
                                                  "id": request_id if isinstance(request_id, str) and len(request_id) <= 200 else ""})


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
    """Ask for more budget on an item, with the amount and the reason. Output: {id, state: "pending", requested_micros}; the poller follows it to approved, denied or expired.

    409 ``budget_request_pending`` (with the open request's ``id``) while an ask is already waiting, on this item here or on the asker's allotment in Argent;
    501 ``budget_request_unavailable`` while Argent's CLI route does not answer for this login (it never expires the login). The reason is never logged or kept here.
    Example: POST /api/v1/argent/budget/requests {"item_id": "wi_story1", "amount_micros": 5000000, "reason": "release week"}
    """
    if feature_on():
        tenant = (get_runtime().store.get_login() or {}).get("tenant_id")
        waiting = await asyncio.to_thread(budget_requests.pending_for, str(tenant), body.item_id) if tenant else None
        if waiting:
            raise _pending(waiting["id"])
    reply, tenant_id = await _post(budget_requests.PATH, {"requested_micros": body.amount_micros, "reason": body.reason, "work_item_id": body.item_id}, budget_ask=True)
    request_id = reply.get("id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 200:
        raise _refuse(502, "argent_refused", "argent gave no request id")
    await asyncio.to_thread(budget_requests.record_filed, tenant_id, request_id, body.item_id, body.amount_micros)
    cost_poller.poke()
    return {"id": request_id, "state": budget_requests.PENDING, "requested_micros": body.amount_micros}


@router.get("/budget/requests")
async def list_budget_requests() -> Dict[str, Any]:
    """The asks this computer filed, newest first. Output: {enabled, requests: [{id, item_id, requested_micros, approved_micros, state (pending, approved, denied, expired), decision_reason, created_at, decided_at}]}.

    Read from the local record (no call to Argent); pushed on ``argent_budget_requests``. Off: {enabled: false, requests: []}. Example: GET /api/v1/argent/budget/requests
    """
    login = get_runtime().store.get_login() if feature_on() else None
    if not login:
        return {"enabled": feature_on(), "requests": []}
    return {"enabled": True, "requests": await asyncio.to_thread(budget_requests.list_records, str(login["tenant_id"]))}


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
