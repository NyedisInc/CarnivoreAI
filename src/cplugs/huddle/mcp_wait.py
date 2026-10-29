
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from src.cplugs.huddle import actor_log, child_hold, wait_resolve, waits
from src.cplugs.huddle.rules import TaskManagerError
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError

ANSWER_KEY = "wait_callback"
ROUTE = "/api/v1/cplugs/huddle/items/{item}/wait/resolve"
SCHEMA: Dict[str, Any] = {
    "waiting_on": {"type": "string", "maxLength": waits.MAX_ON, "description": "REQUIRED with state waiting: what exactly it waits on, short. Not the owner (that is a question: task_manager_ask)."},
    "wait_kind": {"type": "string", "enum": [*waits.KINDS, child_hold.KIND], "description": "REQUIRED with state waiting. children: wait on its open forks (no time; Carnivore clears it)."},
    "expect_by": {"type": "string", "description": "ISO 8601 WITH a UTC offset: when this should be over. Default by kind; required for other."},
    "wait_check": {"type": "object", "description": "A server-run check that clears the wait: {kind: version_live | git_contains | issue_closed | pr_merged | item_state | session_idle | file_exists | url_ok, ...that kind's fields}. Guide section 31."},
    "wait_until": {"type": "string"},
    "extend_reason": {"type": "string", "maxLength": waits.MAX_REASON, "description": "To park again after a lapse (once): why still blocked."},
}
RESOLVE_PROPERTIES: Dict[str, Any] = {
    "item": {"type": "integer"},
    "result": {"type": "string", "enum": list(wait_resolve.RESULTS)},
    "reason": {"type": "string", "maxLength": wait_resolve.MAX_REASON, "description": "OPTIONAL. What cleared, or why it failed."},
}


def park_args(args: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if args.get("state") != "waiting":
        return None
    return {name: args[name] for name in waits.ARGS if name in args}


def wait_answer(item: Mapping[str, Any]) -> Dict[str, Any]:
    token = item.get(waits.TOKEN_KEY)
    live = item.get(waits.FIELD) or {}
    if not token:
        return {}
    return {ANSWER_KEY: {"token": token, "resolve": ROUTE.format(item=item["id"]), "expect_by": live.get("expect_by"), "deadline": live.get("deadline"),
                          "how": "POST the route with JSON {token, result: cleared|failed, reason?}, or call task_manager_wait_update. The token works once and dies with this wait."}}


async def huddle_wait_update(ctx: CplugContext, caller: AgentCaller, args: dict) -> Dict[str, Any]:
    unknown = sorted(set(args) - set(RESOLVE_PROPERTIES))
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    item = args.get("item")
    if isinstance(item, bool) or not isinstance(item, int):
        raise ToolError("item is required: the id of the waiting task")
    by = await actor_log.caller_key(ctx, caller) or ""
    try:
        return await wait_resolve.resolve(ctx, item, args.get("result"), args.get("reason"), authed=True, by_agent=True, by=by)
    except TaskManagerError as exc:
        raise ToolError(str(exc)) from exc

