
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Mapping

from src.cplugs.huddle import flags, own_list, owner_guards
from src.cplugs.sdk import ToolError

MAX_OPS = 50

OPS = ("add", "update", "reply", "ask", "move", "mark_answered", "delete", "fork", "progress")

STEER_KEYS = ("reaches_owner", "reaches_owner_reason", "wait_callback", owner_guards.STORED_AS_ANSWER_TO, owner_guards.GUARD_NOTE)

OpHandler = Callable[[dict], Awaitable[Any]]


def _with_answer_fields(out: Dict[str, Any], payload: Mapping[str, Any]) -> Dict[str, Any]:
    out.update({k: payload[k] for k in own_list.ANSWER_FIELDS if k in payload})
    return out


def lean_of(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if isinstance(payload.get("fork"), Mapping) and isinstance(payload.get("parent"), Mapping):
        return _with_answer_fields({"item_id": payload["parent"]["id"], "ok": True, "fork": lean_of(payload["fork"]), "parent": lean_of(payload["parent"])}, payload)
    item = payload["item"] if isinstance(payload.get("item"), Mapping) else payload
    if item.get("deleted") is True:
        return _with_answer_fields({"item_id": item["id"], "ok": True, "deleted": True, "revision": item.get("revision")}, payload)
    out: Dict[str, Any] = {"item_id": item["id"], "ok": True, "state": item.get("state"), "revision": item.get("revision")}
    if "message_id" in payload:
        out["message_id"] = payload["message_id"]
    for key in STEER_KEYS:
        if key in payload:
            out[key] = payload[key]
    return _with_answer_fields(out, payload)


def _failed(item_id: Any, error: str) -> Dict[str, Any]:
    return {"item_id": item_id, "ok": False, "error": error}


def _check_ops(ops: Any) -> List[dict]:
    if not isinstance(ops, list) or not ops:
        raise ToolError("ops is required: a non-empty list of {op, item_id, ...}")
    if len(ops) > MAX_OPS:
        raise ToolError(f"at most {MAX_OPS} ops per call (got {len(ops)})")
    return ops


async def run(args: dict, *, handlers: Mapping[str, OpHandler], in_list: Callable[[int], Awaitable[None]]) -> Dict[str, Any]:
    """Run every op in order and answer ``{applied, failed, results}``.

    Inputs: args ({ops, stop_on_error?}); handlers ({op name: OpHandler}); in_list (checks an item is in the
      batch's ``list_id``, raises ToolError when it is not).
    Output: dict - ``results`` one lean entry per op, in op order.
    """
    ops = _check_ops(args.get("ops"))
    stop = flags.flag(args, "stop_on_error", False)
    results: List[Dict[str, Any]] = []
    halted = False
    for raw in ops:
        item_id = raw.get("item_id") if isinstance(raw, dict) else None
        if halted:
            results.append(_failed(item_id, "skipped: an earlier op failed and stop_on_error is true"))
            continue
        try:
            results.append(await _one(raw, handlers, in_list))
        except ToolError as exc:
            results.append(_failed(item_id, str(exc)))
            halted = stop
    failed = sum(1 for r in results if not r["ok"])
    return {"applied": len(results) - failed, "failed": failed, "results": results}


async def _one(raw: Any, handlers: Mapping[str, OpHandler], in_list: Callable[[int], Awaitable[None]]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ToolError("each op is an object {op, item_id, ...}")
    name = raw.get("op")
    if name not in handlers:
        raise ToolError(f"op must be one of {', '.join(OPS)}")
    if name == "add":
        return lean_of(await handlers[name]({k: v for k, v in raw.items() if k != "op"}))
    item_id = raw.get("item_id")
    if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id < 1:
        raise ToolError("item_id is required: an item id from task_manager_tasks_list or task_manager_changes")
    await in_list(item_id)
    fields = {k: v for k, v in raw.items() if k not in ("op", "item_id")}
    return lean_of(await handlers[name]({**fields, "item": item_id}))
