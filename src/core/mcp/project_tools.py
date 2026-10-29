
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Optional

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.write_tools import _via_route, park

MAX_NAME_BYTES = 255


def project_id_arg(args: dict) -> int:
    value = args.get("project")
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError("project is required: the id from projects_list")
    return value


async def project_label(project_id: int) -> str:
    try:
        return json.dumps(await _current_name(project_id))
    except ToolError:
        return f"project {project_id}"


def new_name_arg(args: dict) -> str:
    value = args.get("name")
    if not isinstance(value, str) or not value.strip():
        raise ToolError("name is required and must be non-empty text")
    name = value.strip()
    if len(name.encode("utf-8")) > MAX_NAME_BYTES:
        raise ToolError(f"name is over the {MAX_NAME_BYTES} byte limit")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise ToolError("name must not contain control characters")
    return name


async def _names_by_id(*, include_archived: bool = False) -> dict:
    from src.api import projects_service
    from src.config import settings
    from src.models import ProjectResponse

    def read() -> list:
        view = projects_service.current_view(settings, include_archived=include_archived)
        return projects_service.views_to_responses(view, ProjectResponse)

    return {project.id: project.name for project in await asyncio.to_thread(read)}


async def _current_name(project_id: int, *, include_archived: bool = False) -> str:
    names = await _names_by_id(include_archived=include_archived)
    if project_id not in names:
        raise ToolError(f"no project with id {project_id}; see projects_list")
    return names[project_id]


async def project_rename(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import projects_routes
    from src.models import UpdateProjectRequest

    if set(args) - {"project", "name"}:
        raise ToolError("project_rename takes only project and name")
    project_id = project_id_arg(args)
    name = new_name_arg(args)
    old_name = await _current_name(project_id, include_archived=True)

    async def run(approved: bool) -> dict:
        current = await _current_name(project_id, include_archived=True)
        row = await _via_route(projects_routes.update_project(current, UpdateProjectRequest(new_name=name)))
        return _ok({"project": {"id": row.id, "name": row.name, "path": row.path}, "previous_name": current})

    summary = f"rename project {json.dumps(old_name)} to {json.dumps(name)} (display name only; folder and sessions untouched)"
    return await park(manager, caller, "", "", "project_rename", summary, {"project": project_id, "name": name}, run,
                      dedupe_key=f"project_rename:{project_id}:{name}")


def _archive_tool(archive: bool):
    tool = "project_archive" if archive else "project_unarchive"

    async def handler(manager: Any, caller: AgentCaller, args: dict) -> dict:
        from src.api import projects_routes

        if set(args) - {"project"}:
            raise ToolError(f"{tool} takes only project")
        project_id = project_id_arg(args)
        name = await _current_name(project_id, include_archived=True)
        route = projects_routes.archive_project_route if archive else projects_routes.unarchive_project_route

        async def run(approved: bool) -> dict:
            current = await _current_name(project_id, include_archived=True)
            row = await _via_route(route(current))
            return _ok({"project": {"id": row.id, "name": row.name, "archived_at": row.archived_at,
                                    "sessions_archived": row.sessions_archived, "sessions_live": row.sessions_live,
                                    "sessions_restored": row.sessions_restored}})

        verb = "archive" if archive else "restore"
        sessions = ("also archives its asleep and other non-live sessions; running ones stay"
                    if archive else "also restores the sessions its archive archived")
        summary = f"{verb} project {json.dumps(name)} ({sessions}; folder untouched)"
        return await park(manager, caller, "", "", tool, summary, {"project": project_id}, run,
                          dedupe_key=f"{tool}:{project_id}")

    return handler


project_archive = _archive_tool(True)
project_unarchive = _archive_tool(False)


def _move_summary(name: str, plan: dict, flags: dict) -> str:
    how = "rename the folder, then re-point" if flags["move_folder"] else "re-point (folder already there)"
    if plan.get("folders_to_create"):
        how = f"create {', '.join(plan['folders_to_create'])}, then " + how
    counts = (f"{len(plan.get('sessions') or [])} sessions, {len(plan.get('child_projects') or [])} child projects, "
              f"{len(plan.get('transcript_moves') or [])} transcript folders")
    return (f"move project {json.dumps(name)} to {json.dumps(plan.get('new_root'))}: {how} ({counts}; "
            f"plan {plan.get('fingerprint')})")


async def project_move(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import project_move_routes
    from src.models import ProjectMoveRequest

    if set(args) - {"project", "new_root", "move_folder", "create_parents", "apply", "plan_fingerprint"}:
        raise ToolError("project_move takes only project, new_root, move_folder, create_parents, apply "
                        "and plan_fingerprint")
    project_id = project_id_arg(args)
    new_root = args.get("new_root")
    if not isinstance(new_root, str) or not new_root.strip():
        raise ToolError("new_root is required: the project's new folder")
    flags = {key: args.get(key, False) for key in ("move_folder", "create_parents", "apply")}
    if any(not isinstance(value, bool) for value in flags.values()):
        raise ToolError("move_folder, create_parents and apply must be true or false")
    request = SimpleNamespace(app=getattr(manager, "app", None))

    async def route(apply: bool, fingerprint: Optional[str] = None) -> dict:
        current = await _current_name(project_id, include_archived=True)
        body = ProjectMoveRequest(new_root=new_root, move_folder=flags["move_folder"],
                                  create_parents=flags["create_parents"], apply=apply, plan_fingerprint=fingerprint)
        return (await _via_route(project_move_routes.move_project(current, body, request))).model_dump()

    if not flags["apply"]:
        return _ok(await route(False))
    fingerprint = args.get("plan_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        raise ToolError("apply true needs plan_fingerprint: call project_move with apply false, read the plan, "
                        "and pass back its fingerprint")
    fingerprint = fingerprint.strip()
    plan = await route(False)
    if plan["fingerprint"] != fingerprint:
        raise ToolError(f"the plan changed since it was read (fingerprint {fingerprint} is now "
                        f"{plan['fingerprint']}); read the new plan and quote it")
    if not plan["ok"]:
        failed = "; ".join(c["message"] for c in plan["checks"] if not c["ok"])
        raise ToolError(f"the plan does not pass, so nothing was sent for approval: {failed}")
    name = await _current_name(project_id, include_archived=True)

    async def run(approved: bool) -> dict:
        return _ok(await route(True, fingerprint))

    return await park(manager, caller, "", "", "project_move", _move_summary(name, plan, flags),
                      {"project": project_id, "new_root": new_root, "move_folder": flags["move_folder"],
                       "create_parents": flags["create_parents"], "plan_fingerprint": fingerprint}, run,
                      dedupe_key=f"project_move:{project_id}:{new_root}:{fingerprint}")


TOOLS: dict = {
    "project_rename": (
        "Rename a project's display name (id from projects_list). Display name only: the folder, ids, sessions and "
        "tmux names are untouched. A name another project carries is refused. Asks the owner unless Beast Mode is armed.",
        {"project": {"type": "integer", "minimum": 1, "description": "project id from projects_list"},
         "name": {"type": "string", "description": "the new display name (trimmed, 1 to 255 bytes)"}},
        ["project", "name"], project_rename,
    ),
    "project_archive": (
        "Archive a project (id from projects_list): it leaves the default project list and comes back with "
        "project_unarchive. List state only: the folder, ids and sessions are untouched, and a live session keeps "
        "running. Archiving an archived project is a no-op. Asks the owner unless Beast Mode is armed.",
        {"project": {"type": "integer", "minimum": 1, "description": "project id from projects_list"}},
        ["project"], project_archive,
    ),
    "project_unarchive": (
        "Restore an archived project (id from projects_list with archived projects included) to the default "
        "project list. Restoring a live project is a no-op. Asks the owner unless Beast Mode is armed.",
        {"project": {"type": "integer", "minimum": 1, "description": "project id from projects_list"}},
        ["project"], project_unarchive,
    ),
    "project_move": (
        "Move a project's folder (id from projects_list) to new_root. apply false returns the plan and its "
        "fingerprint only, and never waits. apply true needs that plan_fingerprint and asks the owner unless Beast Mode is armed, "
        "then re-points the project, child projects, sessions and transcripts; move_folder true also "
        "renames the folder here. Refused while a session under it is live.",
        {"project": {"type": "integer", "minimum": 1, "description": "project id from projects_list"},
         "new_root": {"type": "string", "description": "the new folder (long spelling is stored)"},
         "move_folder": {"type": "boolean", "description": "rename the folder on this Mac first (default false)"},
         "create_parents": {"type": "boolean",
                            "description": "with move_folder, create the new folder's missing parents (default false)"},
         "apply": {"type": "boolean", "description": "run the move (default false: plan only)"},
         "plan_fingerprint": {"type": "string",
                              "description": "required with apply: the fingerprint of the plan you read"}},
        ["project", "new_root"], project_move,
    ),
}
