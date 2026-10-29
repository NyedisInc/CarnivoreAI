
from __future__ import annotations

from typing import Any, Dict

from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result
from src.cplugs.tmdevtools import commands, service
from src.cplugs.tmdevtools.errors import DevToolsError


SCROLL_TOP_POSITION = "top"


def _refused(exc: DevToolsError) -> ToolError:
    return ToolError(f"refused ({exc.code}): {exc}")


async def task_manager_dev_scroll_set(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    position = args.get("position", SCROLL_TOP_POSITION)
    if position != SCROLL_TOP_POSITION:
        raise ToolError(f"refused (tmdevtools_invalid): position must be {SCROLL_TOP_POSITION!r}")
    try:
        return tool_result(await service.scroll_top(ctx, args.get("list")))
    except DevToolsError as exc:
        raise _refused(exc) from exc


async def task_manager_dev_fold_set(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    try:
        return tool_result(await service.fold(ctx, args))
    except DevToolsError as exc:
        raise _refused(exc) from exc


async def task_manager_dev_tasks_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    try:
        return tool_result(scrub(await service.list_tasks(args)))
    except DevToolsError as exc:
        raise _refused(exc) from exc


_TARGETS: Dict[str, Any] = {
    "items": {"type": "array", "maxItems": service.MAX_TARGETS, "items": {"type": "integer", "minimum": 1}, "description": "Task ids from task_manager_dev_tasks_list."},
    "group": {"description": "A group name or id (or a list of them), searched in project when given, else everywhere.", "anyOf": [
        {"type": "string"}, {"type": "integer"}, {"type": "array", "items": {"type": ["string", "integer"]}}]},
    "project": {"type": "string", "description": "A project name or key. fold/unfold folds its bar, status sections and groups."},
}

TOOLS: dict[str, Any] = {
    "task_manager_dev_scroll_set": ToolSpec(
        description=("Scroll the owner's Task Manager tab to the top in every browser the owner has open. Optionally switch it to one project's list first. "
                     "Changes only what is on their screen."),
        properties={"position": {"type": "string", "enum": [SCROLL_TOP_POSITION], "description": "Where to scroll to. Only top for now (the default)."},
                    "list": {"type": "string", "description": "A project name or key to show first; leave out to keep the list on screen."}},
        required=[], handler=task_manager_dev_scroll_set, gate="agent"),
    "task_manager_dev_fold_set": ToolSpec(
        description=("Fold or unfold things in the owner's Task Manager, or close an opened task card. action fold/unfold takes a group, a project (its bar, "
                     "status sections and groups) or items (a card closes or opens); action close collapses the opened task card back to its row, "
                     "naming items or closing whichever is open. Uses the Task Manager's own fold state; no task changes state. Changes only what is on their screen."),
        properties={"action": {"type": "string", "enum": list(commands.FOLD_ACTIONS)}, **_TARGETS},
        required=["action"], handler=task_manager_dev_fold_set, gate="agent"),
    "task_manager_dev_tasks_list": ToolSpec(
        description=("List tasks (or projects) compactly: id, title, status, project, group, tag. Filter by any combination, for example "
                     "status=question for the open questions, status=open for what is open, project=carnivore for one project. "
                     "view=projects lists the projects with task counts by status. Ticked (done) tasks only show with status=done. Read only."),
        properties={"view": {"type": "string", "enum": [service.VIEW_TASKS, service.VIEW_PROJECTS], "description": "Default tasks."},
                    "project": {"type": "string", "description": "A project name or key (all is the shared list)."},
                    "status": {"type": "string", "description": "question, review, waiting, working, waiting_to_send, scheduled, open, todo or done."},
                    "section": {"type": "string", "description": "The same filter as status."},
                    "group": {"type": "string", "description": "A group name or id."},
                    "tag": {"type": "string", "description": "any, none, or the tagged agent's name."},
                    "kind": {"type": "string", "enum": ["question", "done", "waiting", "info"]}},
        required=[], handler=task_manager_dev_tasks_list, gate="read"),
}
