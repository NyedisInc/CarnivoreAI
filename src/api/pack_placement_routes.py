
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.core.pack.machines import runtime
from src.core.pack.placement import explain, queue as spawn_queue

router = APIRouter(prefix="/pack", tags=["pack-placement"], dependencies=[Depends(require_auth)])


class WorkloadBody(BaseModel):
    """The workload tag: ``kind`` (light, browser, suite, build, render) and the optional size estimates."""

    model_config = ConfigDict(extra="forbid")

    kind: Optional[str] = Field(default=None, max_length=16)
    est_cpu_cores: Optional[float] = Field(default=None, ge=0, le=1024)
    est_ram_gb: Optional[float] = Field(default=None, ge=0, le=1024)
    est_disk_gb: Optional[float] = Field(default=None, ge=0, le=1024)


class ExplainBody(BaseModel):
    """What to place: a workload tag, or a ``task_type`` slug that implies one; the project's name or folder; the tools it needs."""

    model_config = ConfigDict(extra="forbid")

    workload: Optional[WorkloadBody] = None
    task_type: Optional[str] = Field(default=None, max_length=80)
    project: Optional[str] = Field(default=None, max_length=1024)
    needs: List[str] = Field(default_factory=list, max_length=12)


@router.post("/placement/explain")
async def placement_explain(body: ExplainBody, request: Request) -> Dict[str, Any]:
    """Which machine would take this job now, and why; every machine's headroom after its active reserve. Writes nothing."""
    try:
        work = explain.workload_for(body.workload.model_dump(exclude_none=True) if body.workload else None, body.task_type)
    except ValueError as exc:
        raise HTTPException(422, {"code": "workload_invalid", "detail": str(exc)[:300]}) from None
    try:
        decision = await explain.place(explain.Request(work, needs=[n[:32] for n in body.needs], project=body.project),
                                       record_it=False, remote=True)
    except explain.PlacementUnavailable:
        raise HTTPException(503, {"code": "pack_unavailable", "detail": "the Pack machine layer is not running"}) from None
    return decision.as_dict()


def _wired() -> runtime.Wiring:
    wired = runtime.wiring()
    if wired is None:
        raise HTTPException(503, {"code": "pack_unavailable", "detail": "the Pack machine layer is not running"})
    return wired


@router.get("/queue")
async def get_queue(request: Request) -> Dict[str, Any]:
    """The spawn requests waiting for a machine with room (oldest first), each with the reason it last waited."""
    wired = _wired()

    def read() -> List[Dict[str, Any]]:
        with closing(wired.open_db()) as conn:
            return spawn_queue.list_queue(conn)

    rows = await asyncio.to_thread(read)
    return {"queue": [{"id": r["id"], "job": (r["request"].get("args") or {}).get("job"), "queued_at": r["queued_at"],
                       "attempts": r["attempts"], "last_reason": r["last_reason"]} for r in rows]}


@router.delete("/queue/{queue_id}")
async def delete_queue(queue_id: int, request: Request) -> Dict[str, Any]:
    """Cancel one waiting spawn request. 404 when it is not waiting."""
    wired = _wired()

    def cancel() -> bool:
        with closing(wired.open_db()) as conn:
            return spawn_queue.cancel(conn, queue_id)

    if not await asyncio.to_thread(cancel):
        raise HTTPException(404, {"code": "queue_entry_not_waiting", "detail": f"no waiting spawn request {queue_id}"})
    return {"cancelled": queue_id}
