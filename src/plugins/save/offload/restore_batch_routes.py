
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.plugins.save.offload import alerts, batch_routes, push, restore_batch, restore_routes
from src.plugins.save.offload import constants as C
from src.plugins.save.offload.restore_batch import KIND_CONVERSATION, KIND_SESSION, RestoreBatch, RestoreBatchRunner, RestoreStep, Target
from src.plugins.save.service import RUNTIME
from src.plugins.save.vault.manifest import ManifestError, check_unit
from src.plugins.sdk.blob_codec import Throttle

logger = structlog.get_logger()

RUNNER = RestoreBatchRunner()
ID_MAX_LENGTH = 200


def make_pace() -> Throttle:
    return batch_routes.make_pace()


class RestoreBatchBody(BaseModel):
    """What to restore. At least one id in total."""

    session_uuids: List[str] = Field(default_factory=list, description="sessions whose whole offloaded chain comes back", max_length=C.RESTORE_BATCH_MAX)
    conversation_ids: List[str] = Field(default_factory=list, description="single conversations (also ones no session holds)", max_length=C.RESTORE_BATCH_MAX)


class RestoreItemOut(BaseModel):
    """One attempted target."""

    kind: str = Field(description="session | conversation")
    id: str
    status: str = Field(description="restored | failed")
    code: str = Field("", description="why it failed (a restore status or a refusal code)")
    detail: str = ""
    conversations: int = 0
    bytes: int = 0


class RestoreBatchOut(BaseModel):
    """A restore batch and how far it is."""

    id: str
    state: str = Field(description="running | done | stopped")
    planned: int = Field(description="targets this batch was asked to restore")
    restored: int
    failed: int
    bytes: int
    started_at: float
    finished_at: Optional[float] = None
    items: List[RestoreItemOut]


def to_out(batch: RestoreBatch) -> RestoreBatchOut:
    return RestoreBatchOut(id=batch.id, state=batch.state, planned=batch.planned, restored=batch.count(C.ITEM_RESTORED), failed=batch.count(C.ITEM_RESTORE_FAILED), bytes=batch.bytes,
                           started_at=batch.started_at, finished_at=batch.finished_at, items=[RestoreItemOut(**vars(i)) for i in batch.items])


def latest_out() -> Optional[RestoreBatchOut]:
    found = RUNNER.latest()
    return to_out(found) if found is not None else None


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": C.CODE_BAD_TARGETS, "detail": detail, "reasons": [], "stuck": []})


def _ids(values: Iterable[str], what: str) -> List[str]:
    out: List[str] = []
    for raw in values:
        text = str(raw).strip()
        if not text or len(text) > ID_MAX_LENGTH:
            raise _bad(f"each {what} must be 1 to {ID_MAX_LENGTH} characters")
        out.append(text)
    return list(dict.fromkeys(out))


def plan_targets(session_uuids: Sequence[str], conversation_ids: Sequence[str]) -> List[Target]:
    sessions, conversations = _ids(session_uuids, "session id"), _ids(conversation_ids, "conversation id")
    for conversation in conversations:
        try:
            check_unit(conversation)
        except ManifestError as exc:
            raise _bad(f"{conversation[:40]} is not a conversation id: {exc}") from exc
    targets = [Target(KIND_SESSION, s) for s in sessions] + [Target(KIND_CONVERSATION, c) for c in conversations]
    if not targets:
        raise _bad("name at least one session or conversation to restore")
    if len(targets) > C.RESTORE_BATCH_MAX:
        raise _bad(f"at most {C.RESTORE_BATCH_MAX} targets in one restore batch")
    return targets


def _outcome(target: Target, out: restore_routes.RestoreOut) -> RestoreStep:
    bad = [c for c in out.conversations if c.status not in C.RESTORE_OK_STATUSES]
    back = [c for c in out.conversations if c.status in C.RESTORE_OK_STATUSES]
    if bad or not out.conversations:
        first = bad[0] if bad else None
        return RestoreStep(False, first.status if first else "no_vault_point", (first.detail or first.conversation_id) if first else f"nothing to restore for {target.id}", len(back))
    return RestoreStep(True, conversations=len(back), bytes=sum(c.bytes for c in back))


def _restore_once(target: Target) -> restore_routes.RestoreOut:
    if target.kind == KIND_SESSION:
        return restore_routes.run_restore(target.id, None, False)
    return restore_routes.run_restore(None, target.id, False)


def restore_one(target: Target) -> RestoreStep:
    for attempt in range(C.RESTORE_BUSY_RETRIES + 1):
        try:
            return _outcome(target, _restore_once(target))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": str(exc.status_code), "detail": str(exc.detail)}
            code = C.CODE_UNKNOWN_SESSION if exc.status_code == 404 else str(detail.get("code", exc.status_code))
            if code != C.CODE_BUSY or attempt == C.RESTORE_BUSY_RETRIES or RUNNER.wait_stopped(C.RESTORE_BUSY_WAIT_SECONDS):
                return RestoreStep(False, code, str(detail.get("detail", "")))
    return RestoreStep(False, C.CODE_BUSY, "another offload or restore kept running")


def record_alert(batch: RestoreBatch) -> None:
    state_dir = RUNTIME.sources().state_dir
    back = set(batch.restored_ids())
    standing = [str(i) for i in alerts.current(state_dir, alerts.RESTORE).get("conversations") or [] if str(i) not in back]
    alerts.record(state_dir, alerts.RESTORE, blobs=(), conversations=[*standing, *batch.failed_ids()], now=batch.finished_at or 0.0)


def start_batch(session_uuids: Sequence[str], conversation_ids: Sequence[str]) -> RestoreBatchOut:
    targets = plan_targets(session_uuids, conversation_ids)
    try:
        batch = RUNNER.start(targets, restore_one, pace=make_pace(), on_change=push.changed, on_end=record_alert)
    except restore_batch.RestoreBatchBusy as exc:
        raise HTTPException(status_code=409, detail={"code": C.CODE_BATCH_BUSY, "detail": str(exc), "reasons": [], "stuck": []})
    logger.info("offload_restore_batch_started", batch=batch.id, planned=batch.planned)
    push.changed()
    return to_out(batch)


def read_batch(batch_id: str) -> RestoreBatchOut:
    found = RUNNER.get(batch_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no restore batch {batch_id}")
    return to_out(found)


def stop_batch(batch_id: str) -> RestoreBatchOut:
    found = RUNNER.stop(batch_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no restore batch {batch_id}")
    logger.info("offload_restore_batch_stop_requested", batch=batch_id, state=found.state)
    return to_out(found)


def add_to(router: APIRouter) -> None:

    @router.post("/offload/restore-batch", response_model=RestoreBatchOut)
    async def post_restore_batch(body: RestoreBatchBody) -> RestoreBatchOut:
        """Restore many offloaded sessions and conversations, one at a time. Never overwrites, never starts a session; a failed target is recorded and the rest go on."""
        return await run_in_threadpool(start_batch, body.session_uuids, body.conversation_ids)

    @router.get("/offload/restore-batch/{batch_id}", response_model=RestoreBatchOut)
    async def get_restore_batch(batch_id: str) -> RestoreBatchOut:
        """A restore batch's progress and each target's outcome. Read only."""
        return read_batch(batch_id)

    @router.post("/offload/restore-batch/{batch_id}/stop", response_model=RestoreBatchOut)
    async def post_restore_batch_stop(batch_id: str) -> RestoreBatchOut:
        """End a running restore batch after the target in flight. What was already restored stays restored."""
        return stop_batch(batch_id)
