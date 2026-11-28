from __future__ import annotations

import contextlib
import sqlite3
from typing import Any, Callable, Dict, Iterator, Optional

import structlog
from fastapi import Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.plugins.taskmanager import reply, service
from src.plugins.taskmanager.rules import ALL_LIST, TaskManagerAnswerInvalid, TaskManagerError, check_list_key
from src.plugins.sdk import CplugContext, CplugSchemaError, cplug_context, cplug_router

logger = structlog.get_logger()
router = cplug_router("taskmanager")
Ctx = Depends(cplug_context("taskmanager"))


def refusal(exc: TaskManagerError) -> HTTPException:
    body: Dict[str, Any] = {"code": exc.code, "detail": str(exc)}
    current = getattr(exc, "current", None)
    if current is not None:
        body["current"] = current
    reason = getattr(exc, "reason", None)
    if reason is not None:
        body["reason"] = reason
    blocking = getattr(exc, "blocking", None)
    if blocking is not None:
        body["blocking"] = blocking
    if isinstance(exc, TaskManagerAnswerInvalid):
        body["question"] = exc.question
    return HTTPException(status_code=exc.status, detail=body)


@contextlib.contextmanager
def mapped_errors() -> Iterator[None]:
    try:
        yield
    except TaskManagerError as exc:
        raise refusal(exc) from exc
    except (CplugSchemaError, sqlite3.Error, OSError) as exc:
        logger.warning("task_manager_store_unavailable", error=str(exc))
        raise HTTPException(status_code=503, detail={"code": "huddle_unavailable", "detail": str(exc)}) from exc


async def run_store(call: Callable[[], Any]) -> Any:
    with mapped_errors():
        return await run_in_threadpool(call)


async def known_list(ctx: CplugContext, key: str) -> tuple[str, Optional[str]]:
    try:
        check_list_key(key)
    except TaskManagerError as exc:
        raise refusal(exc) from exc
    if key == ALL_LIST:
        return key, None
    names = await run_in_threadpool(service.project_names, ctx)
    if key not in names:
        raise HTTPException(status_code=404, detail={"code": "task_list_unknown", "detail": f"no project {key}"})
    return key, names[key]


async def decide_card(ctx: CplugContext, item: Dict[str, Any], decision: str, owner_message_ref: str = "",
                      note: str = "", *, structured: Optional[Dict[str, Any]] = None) -> None:
    try:
        await reply.decide_card(ctx, item, decision, owner_message_ref, note, structured=structured)
    except TaskManagerError as exc:
        raise refusal(exc) from exc
