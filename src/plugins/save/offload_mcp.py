
from __future__ import annotations

from typing import Any, Dict, Tuple

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from src.plugins.save.offload import batch_routes, constants as C, list_routes, restore_batch_routes, restore_routes
from src.plugins.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result

ROUTE_TOOLS: Dict[str, str] = {
    "/offload": "save_offload_list",
    "/offload/sessions/{session_uuid}/restore": "save_offload_restore",
    "/offload/conversations/{conversation_id}/restore": "save_offload_restore",
    "/offload/batch": "save_offload_batch_start",
    "/offload/batch/{batch_id}": "save_offload_batch_status",
    "/offload/restore-batch": "save_offload_restore_batch_start",
    "/offload/restore-batch/{batch_id}": "save_offload_restore_batch_status",
}


def _refusal(exc: HTTPException) -> ToolError:
    detail = exc.detail
    if isinstance(detail, dict):
        return ToolError(f"{detail.get('code', exc.status_code)}: {str(detail.get('detail', ''))[:300]}")
    return ToolError(f"{exc.status_code}: {str(detail)[:300]}")


def _limit(args: dict) -> int:
    limit = args.get("limit", C.PAGE_DEFAULT)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ToolError(f"limit must be a whole number from 1 to {C.PAGE_MAX}")
    return limit


async def save_offload_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    limit, cursor = _limit(args), args.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise ToolError("cursor must be the next_cursor text of the previous page")
    try:
        page = await run_in_threadpool(list_routes.list_page, args.get("state"), cursor, limit)
    except HTTPException as exc:
        raise _refusal(exc) from exc
    return tool_result(scrub(page.model_dump()))


def _target(args: dict) -> Tuple[str, str]:
    session, conversation = str(args.get("session_uuid") or ""), str(args.get("conversation_id") or "")
    if bool(session) == bool(conversation):
        raise ToolError("name exactly one of session_uuid and conversation_id")
    return ("session", session) if session else ("conversation", conversation)


async def _restore_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    kind, value = _target(args)
    key = "session_uuid" if kind == "session" else "conversation_id"
    what = f"every offloaded conversation of session {value}" if kind == "session" else f"offloaded conversation {value}"
    return {key: value}, f"put {what} back in Claude's folder from the backup vault; nothing is overwritten and no session is started"


async def save_offload_restore(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    kind, value = _target(args)
    try:
        out = await run_in_threadpool(restore_routes.run_restore, value if kind == "session" else None, value if kind == "conversation" else None, False)
    except HTTPException as exc:
        raise _refusal(exc) from exc
    return tool_result(scrub(out.model_dump()))


def _whole(args: dict, key: str, default: int, low: int, high: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ToolError(f"{key} must be a whole number from {low} to {high}")
    return value


async def _batch_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    stage, idle = _whole(args, "max_sessions", 10, 1, C.BATCH_MAX_SESSIONS), _whole(args, "idle_days", C.DEFAULT_IDLE_DAYS, 0, 3650)
    return {"max_sessions": stage, "idle_days": idle}, (f"offload up to {stage} of the oldest closed sessions idle {idle} days or more, one at a time: their transcripts leave Claude's folder "
                                                         f"(verified against the backup vault first, held 7 days, restorable from the offloaded list); it stops at the first failure")


async def save_offload_batch_start(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    stage, idle = _whole(args, "max_sessions", 10, 1, C.BATCH_MAX_SESSIONS), _whole(args, "idle_days", C.DEFAULT_IDLE_DAYS, 0, 3650)
    try:
        out = await run_in_threadpool(batch_routes.start_batch, stage, idle)
    except HTTPException as exc:
        raise _refusal(exc) from exc
    return tool_result(scrub(out.model_dump()))


async def save_offload_batch_status(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    batch_id = args.get("batch_id")
    if batch_id is not None and not isinstance(batch_id, str):
        raise ToolError("batch_id must be the id text start returned")
    try:
        out = batch_routes.read_batch(batch_id) if batch_id else batch_routes.latest_out()
    except HTTPException as exc:
        raise _refusal(exc) from exc
    return tool_result(scrub(out.model_dump() if out is not None else {"batch": None}))


def _id_list(args: dict, key: str) -> list[str]:
    value = args.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolError(f"{key} must be a list of id text")
    return value


async def _restore_batch_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    sessions, conversations = _id_list(args, "session_uuids"), _id_list(args, "conversation_ids")
    try:
        targets = restore_batch_routes.plan_targets(sessions, conversations)
    except HTTPException as exc:
        raise _refusal(exc) from exc
    return ({"session_uuids": [t.id for t in targets if t.kind == "session"], "conversation_ids": [t.id for t in targets if t.kind == "conversation"]},
            f"put back {len(targets)} offloaded items ({sum(t.kind == 'session' for t in targets)} sessions, {sum(t.kind == 'conversation' for t in targets)} conversations) in Claude's folder from the backup vault, one at a "
            f"time; nothing is overwritten and no session is started")


async def save_offload_restore_batch_start(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    try:
        out = await run_in_threadpool(restore_batch_routes.start_batch, _id_list(args, "session_uuids"), _id_list(args, "conversation_ids"))
    except HTTPException as exc:
        raise _refusal(exc) from exc
    return tool_result(scrub(out.model_dump()))


async def save_offload_restore_batch_status(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    batch_id = args.get("batch_id")
    if batch_id is not None and not isinstance(batch_id, str):
        raise ToolError("batch_id must be the id text start returned")
    try:
        out = restore_batch_routes.read_batch(batch_id) if batch_id else restore_batch_routes.latest_out()
    except HTTPException as exc:
        raise _refusal(exc) from exc
    return tool_result(scrub(out.model_dump() if out is not None else {"batch": None}))


_STATE_ENUM: Any = list(C.STATES)
TOOLS: Dict[str, ToolSpec] = {
    "save_offload_list": ToolSpec(
        description="List the sessions whose conversations were offloaded to the backup vault, newest first: name, project, how many conversations, size, when, and state "
                    "(offloaded, restoring, conflict or failed, with the reason). Also says whether the offload setting is on. Read only.",
        properties={"state": {"type": "string", "enum": _STATE_ENUM}, "limit": {"type": "integer", "minimum": 1, "maximum": C.PAGE_MAX},
                    "cursor": {"type": "string", "maxLength": 16}},
        required=[], handler=save_offload_list, gate="read"),
    "save_offload_restore": ToolSpec(
        description="Ask the owner to put an offloaded session's conversations (or one conversation) back in Claude's folder from the backup vault. It starts no session and "
                    "overwrites nothing. It waits for his approval every time.",
        properties={"session_uuid": {"type": "string", "maxLength": 64}, "conversation_id": {"type": "string", "maxLength": 200}},
        required=[], handler=save_offload_restore, gate="inbox", prepare=_restore_prepare, dedupe_by=("session_uuid", "conversation_id")),
    "save_offload_batch_start": ToolSpec(
        description="Ask the owner to start a staged bulk offload: up to max_sessions of the oldest closed sessions idle idle_days or more, offloaded one at a time (stages of 10, then 50, then the rest). "
                    "Their transcripts are verified against the backup vault, moved out of Claude's folder and held 7 days; each can be restored. It waits for the owner's approval every time "
                    "and is refused while the offload setting is off.",
        properties={"max_sessions": {"type": "integer", "minimum": 1, "maximum": C.BATCH_MAX_SESSIONS}, "idle_days": {"type": "integer", "minimum": 0, "maximum": 3650}},
        required=[], handler=save_offload_batch_start, gate="inbox", prepare=_batch_prepare, dedupe_by=("max_sessions", "idle_days")),
    "save_offload_batch_status": ToolSpec(
        description="How far a staged bulk offload is: state (running, done, stopped, failed), counts offloaded, skipped and failed, and each session's outcome. No batch_id means the newest batch. Read only.",
        properties={"batch_id": {"type": "string", "maxLength": 64}},
        required=[], handler=save_offload_batch_status, gate="read"),
    "save_offload_restore_batch_start": ToolSpec(
        description="Ask the owner to put MANY offloaded sessions and/or conversations back in Claude's folder from the backup vault, in one call and with one approval. They are restored one at a time; "
                    "it starts no session and overwrites nothing. A target that cannot be restored is recorded and the rest go on; any failure raises a sticky alert. Name session_uuids and/or conversation_ids.",
        properties={"session_uuids": {"type": "array", "items": {"type": "string", "maxLength": restore_batch_routes.ID_MAX_LENGTH}, "maxItems": C.RESTORE_BATCH_MAX},
                    "conversation_ids": {"type": "array", "items": {"type": "string", "maxLength": restore_batch_routes.ID_MAX_LENGTH}, "maxItems": C.RESTORE_BATCH_MAX}},
        required=[], handler=save_offload_restore_batch_start, gate="inbox", prepare=_restore_batch_prepare),
    "save_offload_restore_batch_status": ToolSpec(
        description="How far a bulk restore is: state (running, done, stopped), counts restored and failed, and each target's outcome. No batch_id means the newest restore batch. Read only.",
        properties={"batch_id": {"type": "string", "maxLength": 64}},
        required=[], handler=save_offload_restore_batch_status, gate="read"),
}
