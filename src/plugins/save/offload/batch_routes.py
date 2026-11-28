
from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.plugins.save.offload import batch as batch_mod
from src.plugins.save.offload import constants as C
from src.plugins.save.offload import offload_routes, push, report, settings
from src.plugins.save.offload.routes import open_install
from src.plugins.save.service import RUNTIME
from src.plugins.save.vault import constants as K
from src.plugins.sdk.blob_codec import Throttle

logger = structlog.get_logger()

RUNNER = batch_mod.BatchRunner()


def make_pace() -> Throttle:
    return Throttle(K.DUTY_CYCLE, K.SLICE_SECONDS)


class BatchBody(BaseModel):
    """How to start a batch."""

    max_sessions: int = Field(description="how many sessions this stage tries at most (Joe's stages: 10, then 50, then the rest)", ge=1, le=C.BATCH_MAX_SESSIONS)
    idle_days: int = Field(C.DEFAULT_IDLE_DAYS, description="a session must have been idle this many days", ge=0, le=3650)


class ItemOut(BaseModel):
    """One attempted session."""

    session_uuid: str
    status: str = Field(description="offloaded | skipped | failed")
    code: str = Field("", description="why it was skipped or failed (a refusal code)")
    detail: str = ""
    conversations: int = 0
    bytes: int = 0


class BatchOut(BaseModel):
    """A batch and how far it is."""

    id: str
    state: str = Field(description="running | done | stopped | failed")
    max_sessions: int
    idle_days: int
    planned: int = Field(description="sessions this batch was asked to try")
    offloaded: int
    skipped: int
    failed: int
    bytes: int
    started_at: float
    finished_at: Optional[float] = None
    items: List[ItemOut]


def to_out(batch: batch_mod.Batch) -> BatchOut:
    return BatchOut(id=batch.id, state=batch.state, max_sessions=batch.max_sessions, idle_days=batch.idle_days, planned=batch.planned,
                    offloaded=batch.count(C.ITEM_OFFLOADED), skipped=batch.count(C.ITEM_SKIPPED), failed=batch.count(C.ITEM_FAILED), bytes=batch.bytes,
                    started_at=batch.started_at, finished_at=batch.finished_at, items=[ItemOut(**vars(i)) for i in batch.items])


def latest_out() -> Optional[BatchOut]:
    found = RUNNER.latest()
    return to_out(found) if found is not None else None


def _refusal(exc: HTTPException) -> batch_mod.StepResult:
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": str(exc.status_code), "detail": str(exc.detail)}
    code = C.CODE_UNKNOWN_SESSION if exc.status_code == 404 else str(detail.get("code", exc.status_code))
    return batch_mod.StepResult(False, code, str(detail.get("detail", "")), stuck=tuple(detail.get("stuck") or ()))


def offload_one(session_uuid: str) -> batch_mod.StepResult:
    try:
        out = offload_routes._run_if_enabled(session_uuid, False)
    except HTTPException as exc:
        return _refusal(exc)
    return batch_mod.StepResult(True, conversations=len(out.conversations), bytes=out.bytes)


def _plan(max_sessions: int, idle_days: int) -> List[str]:
    evaluator, ready = open_install()
    if not ready.ready:
        raise HTTPException(status_code=409, detail={"code": C.CODE_NOT_READY, "detail": "the install is not ready to offload: " + ", ".join(ready.blockers),
                                                     "reasons": list(ready.blockers), "stuck": []})
    page = report.build_page(evaluator, ready, idle_days, None, max_sessions)
    return [v.session_uuid for v in page.candidates]


def start_batch(max_sessions: int, idle_days: int) -> BatchOut:
    settings.require_enabled(RUNTIME.sources().state_dir)
    planned = _plan(max_sessions, idle_days)
    try:
        batch = RUNNER.start(planned, offload_one, max_sessions=max_sessions, idle_days=idle_days, pace=make_pace(), on_change=push.changed)
    except batch_mod.BatchBusy as exc:
        raise HTTPException(status_code=409, detail={"code": C.CODE_BATCH_BUSY, "detail": str(exc), "reasons": [], "stuck": []})
    logger.info("offload_batch_started", batch=batch.id, planned=batch.planned, max_sessions=max_sessions, idle_days=idle_days)
    push.changed()
    return to_out(batch)


def read_batch(batch_id: str) -> BatchOut:
    found = RUNNER.get(batch_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no batch {batch_id}")
    return to_out(found)


def stop_batch(batch_id: str) -> BatchOut:
    found = RUNNER.stop(batch_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no batch {batch_id}")
    logger.info("offload_batch_stop_requested", batch=batch_id, state=found.state)
    return to_out(found)


def add_to(router: APIRouter) -> None:

    @router.post("/offload/batch", response_model=BatchOut)
    async def post_batch(body: BatchBody) -> BatchOut:
        """Start a staged bulk offload: the oldest idle sessions, one at a time, stopping at the first failure. 409 ``offload_disabled`` while the offload switch is off (the default)."""
        return await run_in_threadpool(start_batch, body.max_sessions, body.idle_days)

    @router.get("/offload/batch/{batch_id}", response_model=BatchOut)
    async def get_batch(batch_id: str) -> BatchOut:
        """A batch's progress and each session's outcome. Read only."""
        return read_batch(batch_id)

    @router.post("/offload/batch/{batch_id}/stop", response_model=BatchOut)
    async def post_batch_stop(batch_id: str) -> BatchOut:
        """End a running batch after the session in flight. The files of finished sessions stay offloaded; restore puts them back."""
        return stop_batch(batch_id)
