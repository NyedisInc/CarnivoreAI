
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from typing import Any, Optional

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.project_tools import project_label
from src.core.mcp.write_tools import _via_route, park

MAX_COMPANY_NAME = 80


def _id_arg(args: dict, key: str, *, nullable: bool = False) -> Optional[int]:
    if key not in args:
        raise ToolError(f"{key} is required")
    value = args[key]
    if value is None and nullable:
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError(f"{key} must be a positive id" + (", or null" if nullable else ""))
    return value


def _name_arg(args: dict) -> str:
    value = args.get("name")
    if not isinstance(value, str) or not value.strip():
        raise ToolError("name is required and must be non-empty text")
    name = value.strip()
    if len(name) > MAX_COMPANY_NAME:
        raise ToolError(f"name is over the {MAX_COMPANY_NAME} character limit")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise ToolError("name must not contain control characters")
    return name


def _only(args: dict, tool: str, allowed: set) -> None:
    extra = set(args) - allowed
    if extra:
        raise ToolError(f"{tool} takes only {', '.join(sorted(allowed))}")


async def company_label(company_id: int) -> str:
    from src.config import settings
    from src.core.companies import store
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    def read() -> Optional[str]:
        with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
            return store.get_company(conn, company_id)["name"]

    try:
        return json.dumps(await asyncio.to_thread(read))
    except (store.CompanyNotFound, DatastoreUnreadableError):
        return f"company {company_id}"


def _company_out(row: Any) -> dict:
    return {"id": row["id"], "name": row["name"], "parent_id": row.get("parent_id"), "hq_project_id": row.get("hq_project_id")}


async def company_create(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import companies_routes

    _only(args, "company_create", {"name", "parent_id"})
    name = _name_arg(args)
    parent_id = _id_arg(args, "parent_id", nullable=True) if "parent_id" in args else None

    async def run(approved: bool) -> dict:
        body = companies_routes.CompanyNameRequest(name=name, parent_id=parent_id)
        return _ok({"company": _company_out(await _via_route(companies_routes.create_company(body)))})

    where = "at the top level" if parent_id is None else f"under {await company_label(parent_id)}"
    return await park(manager, caller, "", "", "company_create", f"create company {json.dumps(name)} {where}",
                      {"name": name, "parent_id": parent_id}, run,
                      dedupe_key=f"company_create:{name.casefold()}:{parent_id}")


async def _patch(manager: Any, caller: AgentCaller, tool: str, company_id: int, field: str, value: Any, summary: str) -> dict:
    from src.api import companies_routes

    async def run(approved: bool) -> dict:
        body = companies_routes.CompanyPatchRequest(**{field: value})
        return _ok({"company": _company_out(await _via_route(companies_routes.rename_company(company_id, body)))})

    return await park(manager, caller, "", "", tool, summary, {"company_id": company_id, field: value}, run,
                      dedupe_key=f"{tool}:{company_id}:{value}")


def _color_arg(args: dict) -> str:
    from src.core.project_colors.palette import is_hex_color, normalize_color

    color = args.get("color")
    if not is_hex_color(color):
        raise ToolError(f"color must be a #rrggbb hex, got {json.dumps(color)[:40]}")
    return normalize_color(color)


async def company_color_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    _only(args, "company_color_set", {"company_id", "color"})
    company_id = _id_arg(args, "company_id")
    color = _color_arg(args)
    summary = f"set company {await company_label(company_id)}'s color to {color} (its Swarm color family follows the hue)"
    return await _patch(manager, caller, "company_color_set", company_id, "color", color, summary)


async def company_rename(manager: Any, caller: AgentCaller, args: dict) -> dict:
    _only(args, "company_rename", {"company_id", "name"})
    company_id, name = _id_arg(args, "company_id"), _name_arg(args)
    summary = f"rename {await company_label(company_id)} to {json.dumps(name)} (its projects stay filed under it)"
    return await _patch(manager, caller, "company_rename", company_id, "name", name, summary)


async def company_parent_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    _only(args, "company_parent_set", {"company_id", "parent_id"})
    company_id, parent_id = _id_arg(args, "company_id"), _id_arg(args, "parent_id", nullable=True)
    if parent_id == company_id:
        raise ToolError("a company cannot be its own parent")
    where = "the top level" if parent_id is None else f"under {await company_label(parent_id)}"
    summary = f"move {await company_label(company_id)} and every company under it to {where}"
    return await _patch(manager, caller, "company_parent_set", company_id, "parent_id", parent_id, summary)


async def company_hq_set(manager: Any, caller: AgentCaller, args: dict) -> dict:
    _only(args, "company_hq_set", {"company_id", "project_id"})
    company_id, project_id = _id_arg(args, "company_id"), _id_arg(args, "project_id", nullable=True)
    company = await company_label(company_id)
    if project_id is None:
        summary = f"clear the HQ project of {company} (folders and sessions untouched)"
    else:
        summary = f"make {await project_label(project_id)} (project) the HQ project of {company} (folders and sessions untouched)"
    return await _patch(manager, caller, "company_hq_set", company_id, "hq_project_id", project_id, summary)


async def company_delete(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import companies_routes

    _only(args, "company_delete", {"company_id"})
    company_id = _id_arg(args, "company_id")

    async def run(approved: bool) -> dict:
        answer = await _via_route(companies_routes.delete_company(company_id))
        return _ok(answer.model_dump())

    summary = (f"delete {await company_label(company_id)} (its projects become orphaned and its child companies move up "
               "a level; no folder or session is touched)")
    return await park(manager, caller, "", "", "company_delete", summary, {"company_id": company_id}, run,
                      dedupe_key=f"company_delete:{company_id}", beast_eligible=False)


_COMPANY_ID = {"type": "integer", "minimum": 1, "description": "company id from companies_list"}
_WAITS = "Asks the owner unless Beast Mode is armed."

TOOLS: dict = {
    "company_create": (
        "Create a company, at the top level or under parent_id (companies nest at most four levels). " + _WAITS,
        {"name": {"type": "string", "description": "the company name (trimmed, 1 to 80 characters, unique)"},
         "parent_id": {"type": ["integer", "null"], "minimum": 1,
                       "description": "company id from companies_list to create it under; omit or null for the top level"}},
        ["name"], company_create,
    ),
    "company_rename": (
        "Rename a company (company_id from companies_list). Its projects and child companies stay where they are. " + _WAITS,
        {"company_id": _COMPANY_ID, "name": {"type": "string", "description": "the new name (1 to 80 characters, unique)"}},
        ["company_id", "name"], company_rename,
    ),
    "company_parent_set": (
        "Move a company and everything under it under another company, or to the top level with parent_id null. A cycle "
        "or a tree deeper than four levels is refused. " + _WAITS,
        {"company_id": _COMPANY_ID,
         "parent_id": {"type": ["integer", "null"], "minimum": 1,
                       "description": "company id from companies_list, or null for the top level"}},
        ["company_id", "parent_id"], company_parent_set,
    ),
    "company_hq_set": (
        "Set a company's HQ project (project_id from projects_list, the company agent's home folder), or clear it with "
        "null. " + _WAITS,
        {"company_id": _COMPANY_ID,
         "project_id": {"type": ["integer", "null"], "minimum": 1, "description": "project id from projects_list, or null"}},
        ["company_id", "project_id"], company_hq_set,
    ),
    "company_delete": (
        "Delete a company: its projects become orphaned (never deleted) and its child companies move up to its parent. "
        "No folder or session is touched. Always waits for the owner's approval.",
        {"company_id": _COMPANY_ID},
        ["company_id"], company_delete,
    ),
}
