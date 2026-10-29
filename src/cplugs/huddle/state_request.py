
from __future__ import annotations

import asyncio
from typing import Any, Dict, Tuple

import structlog

from src.cplugs.huddle import closure_undo, flags, own_list, rules, send_queue, service
from src.cplugs.huddle.rules import CLAUDE, JOE, TaskManagerError
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError

logger = structlog.get_logger()

TOOL = "task_manager_state_request"
REOPEN = "reopen"
CLOSE = "close"
DELETE = "delete"
UNDO = "undo_completion"
ACTIONS = (REOPEN, CLOSE, DELETE, UNDO)
PRIOR = "its prior state"
DELETED = "deleted"
REOPEN_TARGETS = (rules.OPEN, rules.WAITING)
MAX_REASON = 500
MAX_TITLE = 80
DEDUPE_BY = ("item",)


def _title_of(item: Dict[str, Any]) -> str:
    text = str(item.get("title") or (str(item.get("text") or "").strip().splitlines() or [""])[0])
    return text if len(text) <= MAX_TITLE else text[: MAX_TITLE - 3] + "..."


def _target_of(action: str, args: dict, item: Dict[str, Any]) -> str:
    if action == DELETE:
        if args.get("to_state") not in (None, ""):
            raise ToolError("delete has no to_state; the item is removed for good once the owner approves")
        return DELETED
    if action == UNDO:
        if args.get("to_state") not in (None, ""):
            raise ToolError("undo_completion has no to_state; the task returns to the state it had before it was closed")
        return PRIOR
    if action == CLOSE:
        if args.get("to_state") not in (None, "", rules.DONE):
            raise ToolError("close always ends done (the owner's approve of this request is his tick); do not send to_state")
        return rules.DONE
    target = args.get("to_state") or rules.OPEN
    if target not in REOPEN_TARGETS:
        raise ToolError(f"reopen goes to {' or '.join(REOPEN_TARGETS)}, not {target!r}")
    return target


async def prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    clean = rules.canonical_state_args({k: v for k, v in args.items() if k != own_list.FIELD})
    unknown = sorted(set(clean) - {"item", "action", "reason", "to_state"})
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}; send item, action, reason and (reopen only) to_state")
    item_id, action = clean.get("item"), clean.get("action")
    if isinstance(item_id, bool) or not isinstance(item_id, int):
        raise ToolError("item is required: an item id from task_manager_tasks_list")
    if action not in ACTIONS:
        raise ToolError(f"action must be {REOPEN}, {CLOSE}, {DELETE} or {UNDO}")
    try:
        reason = rules.clean_text(clean.get("reason"), "reason", MAX_REASON)
        item = await asyncio.to_thread(service.store(ctx).item, item_id)
        rules.check_not_swarm_card(CLAUDE, item["swarm_ref"])
    except TaskManagerError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc
    await own_list.judge(ctx, caller, await own_list.targets(ctx, {"item": item_id}), flags.flag(args, own_list.FIELD, False))
    current = item["state"]
    if action in (REOPEN, UNDO) and current not in rules.APPROVED_STATES:
        raise ToolError(f"item {item_id} is {current}, not approved; change its state yourself with task_manager_update")
    if action == CLOSE and current in rules.APPROVED_STATES:
        raise ToolError(f"item {item_id} is already approved")
    target = _target_of(action, clean, item)
    title = _title_of(item)
    shown = {"item": item_id, "title": title, "action": action, "from_state": current, "to_state": target, "reason": reason}
    sentence = (f"delete huddle item {item_id} {title!r} for good (thread, history and files). reason: {reason}" if action == DELETE
                else f"{action} huddle item {item_id} {title!r}: {current} to {target}. reason: {reason}")
    return shown, sentence


def canonical_shown(args: dict) -> dict:
    clean = rules.canonical_state_args(args)
    if "from_state" in clean:
        clean["from_state"] = rules.canonical_state(clean["from_state"])
    return clean


def _record(ctx: CplugContext, item_id: int, text: str) -> None:
    service.store(ctx).post(item_id, text, actor=CLAUDE, kind="info")


def _wording(args: dict) -> str:
    return f"{args['action']} ({args['from_state']} to {args['to_state']}), reason: {args['reason']}"


async def apply(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    store = service.store(ctx)
    item_id = args["item"]
    try:
        item = await asyncio.to_thread(store.item, item_id)
        if item["state"] != rules.canonical_state(args["from_state"]):
            note = f"not applied: the item is {item['state']} now, not {args['from_state']}"
            await asyncio.to_thread(_record, ctx, item_id, f"the owner approved claude's request to {_wording(args)}, but {note}.")
            return {"applied": False, "item": item_id, "state": item["state"], "reason": note}
        if args["action"] == DELETE:
            await asyncio.to_thread(lambda: store.delete(item_id, actor=JOE))
            logger.info("task_manager_state_request_applied", item=item_id, action=DELETE)
            return {"applied": True, "item": item_id, "action": DELETE, "from_state": args["from_state"], "state": DELETED}
        if args["action"] == UNDO:
            done = await asyncio.to_thread(lambda: closure_undo.undo_completion(store, item_id, item["revision"]))
            await send_queue.queue_owner_write(ctx, done["item"])
            logger.info("task_manager_state_request_applied", item=item_id, action=UNDO, state=done["item"]["state"])
            return {"applied": True, "item": item_id, "action": UNDO, "from_state": args["from_state"], "state": done["item"]["state"],
                    "retraction": done["message"]["text"]}
        if args["action"] == CLOSE:
            changed = await asyncio.to_thread(lambda: store.update(item_id, actor=JOE, approve=True))
        else:
            changed = await asyncio.to_thread(lambda: store.update(item_id, actor=JOE, state=args["to_state"]))
        await asyncio.to_thread(_record, ctx, item_id, f"the owner approved claude's request to {_wording(args)}. it is {changed['state']} now.")
    except rules.TaskManagerNotAllowed as exc:
        note = f"not applied: {exc}"
        await asyncio.to_thread(_record, ctx, item_id, f"the owner approved claude's request to {_wording(args)}, but {note}.")
        return {"applied": False, "item": item_id, "state": item["state"], "reason": note}
    except TaskManagerError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc
    logger.info("task_manager_state_request_applied", item=item_id, action=args["action"], state=changed["state"])
    return {"applied": True, "item": item_id, "action": args["action"], "from_state": args["from_state"], "state": changed["state"]}


def on_deny(ctx: CplugContext, args: dict) -> None:
    try:
        _record(ctx, args["item"], f"the owner denied claude's request to {_wording(args)}. the item stays {args['from_state']}.")
    except (TaskManagerError, KeyError) as exc:
        logger.warning("task_manager_state_request_deny_unrecorded", item=args.get("item"), error=str(exc)[:200])
