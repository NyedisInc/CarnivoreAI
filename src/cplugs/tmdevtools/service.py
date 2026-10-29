
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.cplugs.sdk import CplugContext
from src.cplugs.tmdevtools import commands, ports
from src.cplugs.tmdevtools.errors import BadArguments, DevToolsError, NoTaskManager, NotFound

VIEW_TASKS, VIEW_PROJECTS = "tasks", "projects"
MAX_TARGETS = 100


def _port() -> ports.DevToolsPort:
    try:
        return ports.get()
    except ports.TaskManagerOff as exc:
        raise NoTaskManager(str(exc)) from exc


def _ints(value: Any, name: str) -> List[int]:
    raw = [] if value is None else value if isinstance(value, list) else [value]
    if len(raw) > MAX_TARGETS or any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in raw):
        raise BadArguments(f"{name} must be up to {MAX_TARGETS} task ids (whole numbers from task_manager_dev_tasks_list)")
    return raw


def _names(value: Any, name: str) -> List[str]:
    raw = [] if value is None else value if isinstance(value, list) else [value]
    if len(raw) > MAX_TARGETS or any(isinstance(v, bool) or not isinstance(v, (str, int)) or not str(v).strip() for v in raw):
        raise BadArguments(f"{name} must be up to {MAX_TARGETS} group names or ids")
    return [str(v).strip() for v in raw]


def _text(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BadArguments(f"{name} must be a non-empty string")
    return value.strip()


async def scroll_top(ctx: CplugContext, list_key: Any = None) -> Dict[str, Any]:
    name = _text(list_key, "list")
    key = None
    if name is not None:
        found = await _port().resolve(project=name)
        if "error" in found:
            raise NotFound(found["error"])
        key = found["list"]
    command = commands.send(ctx, commands.SCROLL_TOP, list=key)
    return {"sent": True, "seq": command["seq"], "list": key}


async def fold(ctx: CplugContext, args: Dict[str, Any]) -> Dict[str, Any]:
    action = args.get("action")
    if action not in commands.FOLD_ACTIONS:
        raise BadArguments(f"action must be one of {', '.join(commands.FOLD_ACTIONS)}")
    items = _ints(args.get("items"), "items")
    groups = _names(args.get("group"), "group")
    project = _text(args.get("project"), "project")
    if action == "close" and (groups or (project and not items)):
        raise BadArguments("close collapses an opened task card; use fold for a group or a project")
    if action != "close" and not (items or groups or project):
        raise BadArguments("name what to fold: items, group or project")
    found = await _port().resolve(project=project, groups=groups, items=items) if (items or groups or project) else {"list": None, "groups": [], "items": []}
    if "error" in found:
        raise NotFound(found["error"])
    scope_project = found["list"] if project and not groups else None
    command = commands.send(ctx, commands.FOLD, action=action, items=found["items"], groups=found["groups"], project=scope_project)
    return {"sent": True, "seq": command["seq"], "action": action, "items": found["items"], "groups": found["groups"], "project": found.get("project") if scope_project else None}


async def list_tasks(args: Dict[str, Any]) -> Dict[str, Any]:
    view = args.get("view") or VIEW_TASKS
    if view not in (VIEW_TASKS, VIEW_PROJECTS):
        raise BadArguments("view must be tasks or projects")
    port = _port()
    if view == VIEW_PROJECTS:
        return {"projects": await port.projects()}
    status = _text(args.get("status"), "status")
    section = _text(args.get("section"), "section")
    if status and section and status.casefold() != section.casefold():
        raise BadArguments("status and section are the same filter; pass one")
    answer = await port.tasks(project=_text(args.get("project"), "project"), status=status or section, group=_text(args.get("group"), "group"),
                              tag=_text(args.get("tag"), "tag"), kind=_text(args.get("kind"), "kind"))
    if "error" in answer:
        raise NotFound(answer["error"])
    return answer


__all__ = ["DevToolsError", "fold", "list_tasks", "scroll_top"]
