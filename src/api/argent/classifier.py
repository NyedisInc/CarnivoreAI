
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.argent.context import _tmux_name
from src.api.argent.status import feature_on
from src.api.auth import require_auth
from src.core.argent import classifier
from src.core.argent.classifier_signals import gather

router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])


class ClassifierSetting(BaseModel):
    """Example: {"ask_every_time": true}"""

    model_config = ConfigDict(extra="forbid")

    ask_every_time: bool


class ClassifyRequest(BaseModel):
    """Example: {"last_prompt": "make login redo the token"}; the prompt is the caller's (the server does not store prompts here)."""

    model_config = ConfigDict(extra="forbid")

    last_prompt: str = Field("", max_length=20000)


def _off() -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "feature_off", "message": "turn the argent feature on first"})


@router.get("/classifier")
async def get_classifier() -> Dict[str, Any]:
    """Output: {enabled, ask_every_time, connected} (connected: a byoai connection serves the helper ai). Example: GET /api/v1/argent/classifier"""
    if not feature_on():
        return {"enabled": False, "ask_every_time": False, "connected": False}
    return {"enabled": True, "ask_every_time": await run_in_threadpool(classifier.ask_every_time), "connected": await run_in_threadpool(classifier.has_connection)}


@router.put("/classifier")
async def put_classifier(body: ClassifierSetting) -> Dict[str, Any]:
    """Set "ask every time". Raises: 409 ``feature_off``. Example: PUT /api/v1/argent/classifier {"ask_every_time": true}"""
    if not feature_on():
        raise _off()
    await run_in_threadpool(classifier.set_ask_every_time, body.ask_every_time)
    return {"enabled": True, "ask_every_time": body.ask_every_time}


@router.post("/sessions/{session_id}/classify")
async def classify_session(request: Request, session_id: str, body: Optional[ClassifyRequest] = None) -> Dict[str, Any]:
    """Classify one local session now. Output: {action, reason, work_item_id, confidence}. Raises: 409 ``feature_off``, 404, 409 for a remote row.

    Example: POST /api/v1/argent/sessions/ses_abc/classify {"last_prompt": "make login redo the token"}
    """
    if not feature_on():
        raise _off()
    name = await _tmux_name(request, session_id)
    info = await request.app.state.session_manager.get_session_info(session_id)
    directory = str(info.session.working_dir or "") if info is not None and info.session is not None else ""
    signals = await gather(directory, body.last_prompt if body else "")
    outcome = await classifier.classify(name, signals, display_name=str(getattr(info, "display_name", "") or ""))
    return {"action": outcome.action, "reason": outcome.reason, "work_item_id": outcome.work_item_id, "confidence": outcome.confidence}
