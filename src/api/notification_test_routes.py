
from __future__ import annotations

import platform
import time
from typing import Any, Dict, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_auth
from src.core.notifications import engine, routing_view, test_toast, types

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


class TestBody(BaseModel):
    """``POST .../test``: an optional ``type_id`` makes the test that type's sample card (422 for an unregistered type)."""

    model_config = ConfigDict(extra="forbid")

    type_id: Optional[str] = None


@router.post("/destinations/{dest_id}/test")
async def post_test(dest_id: str, body: Optional[TestBody] = None) -> Dict[str, Optional[Union[bool, str, int]]]:
    """Send the test message (a type's sample card when ``type_id`` is given).

    Output: {ok, failure, status_code}; raises 503, 404, 422 (bad type) or 429 as described above.
    """
    type_id = body.type_id if body else None
    if type_id is not None:
        type_id = types.canonical(type_id)
        if not types.is_registered(type_id):
            raise HTTPException(status_code=422, detail="not a notification type")
    active = engine.current_engine()
    if active is None:
        raise HTTPException(status_code=503, detail="notifications are not running")
    outcome = await active.send_test(dest_id, type_id)
    if not outcome.found:
        raise HTTPException(status_code=404, detail="unknown destination")
    if outcome.limited:
        raise HTTPException(status_code=429, detail="test sent too recently")
    result = outcome.result
    return {"ok": result.ok, "failure": result.failure.value if result.failure else None,
            "status_code": result.status_code}


TEST_WINDOW_SECONDS = 10.0
_last: Dict[tuple, float] = {}


class TypedTestBody(BaseModel):
    """``POST /notifications/test``: test this type to my phone, this computer's desktop or the carnivore app (always this computer)."""

    model_config = ConfigDict(extra="forbid")

    type_id: str
    target: Literal["phone", "desktop", "app"]


def _limited(target: str, type_id: str) -> bool:
    now = time.monotonic()
    last = _last.get((target, type_id))
    if last is not None and now - last < TEST_WINDOW_SECONDS:
        return True
    _last[(target, type_id)] = now
    return False


@router.post("/test")
async def post_typed_test(body: TypedTestBody, request: Request) -> Dict[str, Any]:
    """Send the sample card of a type to ONE target on this computer, ignoring ticks, pause, quiet hours and the master switch.

    Output: {ok, failure, status_code, target, delivered}. 422 bad type or target, 404 ``no_phone``, 429 inside the window, 503 engine off
    (and, for app and desktop, 409 ``no_session`` when no session is live to carry the toast).
    """
    type_id = types.canonical(body.type_id)
    if not types.is_registered(type_id):
        raise HTTPException(status_code=422, detail={"error": "bad_value"})
    active = engine.current_engine()
    if active is None:
        raise HTTPException(status_code=503, detail={"error": "notifications_off"})
    if body.target == "phone":
        view = routing_view.current_view()
        pushes = [d.id for d in view.destinations() if d.kind in ("webpush", "apns")] if view is not None else []
        if not pushes:
            raise HTTPException(status_code=404, detail={"error": "no_phone"})
        if _limited("phone", type_id):
            raise HTTPException(status_code=429, detail={"error": "too_soon"})
        outcomes = [await active.send_test(dest_id, type_id) for dest_id in pushes]
        if all(o.limited for o in outcomes):
            raise HTTPException(status_code=429, detail={"error": "too_soon"})
        ok = [o for o in outcomes if o.result is not None and o.result.ok]
        failed = next((o.result for o in outcomes if o.result is not None and not o.result.ok), None)
        return {"ok": bool(ok), "failure": failed.failure.value if failed is not None and failed.failure else None,
                "status_code": failed.status_code if failed is not None else None, "target": "phone", "delivered": len(ok)}
    if _limited(body.target, type_id):
        raise HTTPException(status_code=429, detail={"error": "too_soon"})
    manager = getattr(request.app.state, "session_manager", None)
    toast = test_toast.record(manager, type_id, body.target, platform.node().split(".")[0][:64]) if manager is not None else None
    if toast is None:
        _last.pop((body.target, type_id), None)
        raise HTTPException(status_code=409, detail={"error": "no_session"})
    await test_toast.broadcast(toast, request.app.state)
    return {"ok": True, "failure": None, "status_code": None, "target": body.target, "delivered": 1}
