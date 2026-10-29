
from __future__ import annotations

import asyncio
from typing import Any, Dict

from src.cplugs.huddle import actor_log, file_removal, files, own_list
from src.cplugs.huddle.rules import TaskManagerError
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, tool_result

NAME = "task_manager_file_remove"
DESCRIPTION = ("Delete one file YOU attached to a task (a task_manager_reply file_paths file): the thread says it was removed and its bytes go. Only the attaching agent or the owner may. "
               "Refused, nothing changed: task_manager_file_shared (another author or task names it), task_manager_file_on_board (use task_manager_board_attachment_remove), "
               "task_manager_file_unsafe. task_manager_bytes_not_removed: call again.")
SCHEMA: Dict[str, Any] = {
    "item": {"type": "integer", "description": "The task's item id."},
    "file_id": {"type": "string", "description": "The file's 8 hex character id."},
    **own_list.SCHEMA,
}


@own_list.guarded()
async def _remove(ctx: CplugContext, caller: AgentCaller, args: dict) -> Dict[str, Any]:
    unknown = sorted(set(args) - {"item", "file_id"})
    if unknown or isinstance(args.get("item"), bool) or not isinstance(args.get("item"), int) or not isinstance(args.get("file_id"), str):
        raise ToolError("pass item (an item id) and file_id (the file's 8 hex id) only" + (f"; unknown: {', '.join(unknown)}" if unknown else ""))
    key = await actor_log.caller_key(ctx, caller) or ""
    try:
        return await asyncio.to_thread(file_removal.remove, ctx, args["item"], args["file_id"], agent_key=key)
    except TaskManagerError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc


async def task_manager_file_remove(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return tool_result(await _remove(ctx, caller, args))


TOOLS: Dict[str, ToolSpec] = {
    NAME: ToolSpec(DESCRIPTION, SCHEMA, ["item", "file_id"], task_manager_file_remove, "agent"),
}

__all__ = ["NAME", "TOOLS", "task_manager_file_remove"]
