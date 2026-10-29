
from __future__ import annotations

import asyncio
import json
from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError, _ok
from src.core.mcp.write_tools import _request, _via_route, park


async def skills_command_center(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import skills_command_routes

    if set(args) - {"include_archived"}:
        raise ToolError("only include_archived is accepted")
    include = args.get("include_archived", False)
    if not isinstance(include, bool):
        raise ToolError("include_archived must be true or false")
    return _ok(await _via_route(skills_command_routes.get_command_center(_request(manager), include)))


async def skill_copy(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import skills_command_routes as routes

    allowed = {"source_location_id", "source_column_id", "targets", "dry_run", "generation", "source_digest", "include_archived"}
    if set(args) - allowed:
        raise ToolError("unknown argument; accepted: " + ", ".join(sorted(allowed)))
    try:
        body = routes.CopyRequest(**{**args, "dry_run": args.get("dry_run", True)})
    except ValueError as exc:
        raise ToolError(f"invalid arguments: {exc.__class__.__name__}") from None
    if body.dry_run:
        return _ok(await _via_route(routes.post_copy(_request(manager), body)))
    preview = await _via_route(routes.post_copy(_request(manager), body.model_copy(update={"dry_run": True})))
    if (body.generation, body.source_digest) != (preview["generation"], preview["source"]["source_digest"]):
        raise ToolError("stale: the skills changed since the dry run; run it again")
    src = preview["source"]
    q = json.dumps

    def names(items: list) -> str:
        shown = ", ".join(q(i[:120]) for i in items[:10])
        return (shown + (f" and {len(items) - 10} more" if len(items) > 10 else "")) if items else "none"

    plan = "; ".join(f"{q(r['label'][:80])} ({r['status']}"
                     + (f", shared by logins {names(r['accounts_sharing'])}" if len(r.get("accounts_sharing", [])) > 1 else "") + ")"
                     for r in preview["results"][:20])
    summary = (f"copy the local skill {q(src['name'])} (folder {q(src['folder'])}, {src['files']} files) from "
               f"{q(src['label'][:80])} ({src['scope']}, {src['harness']}) to: {plan}. "
               f"Scripts copied as they are: {names(src['scripts'])}; executable files: {names(src['exec_files'])}. "
               "A replaced folder moves to that root's trash.")

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(routes.post_copy(_request(manager), body)))

    return await park(manager, caller, "", "", "skill_copy", summary, args, run,
                      dedupe_key=f"skill_copy:{src['source_digest']}:{body.source_column_id}", beast_eligible=False)


async def skill_remove(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import skills_command_routes as routes

    allowed = {"location_id", "column_id", "generation", "include_archived"}
    if set(args) - allowed:
        raise ToolError("unknown argument; accepted: " + ", ".join(sorted(allowed)))
    try:
        body = routes.RemoveCellRequest(**args)
    except ValueError as exc:
        raise ToolError(f"invalid arguments: {exc.__class__.__name__}") from None
    matrix = await _via_route(asyncio.to_thread(routes.command_center_now, _request(manager), body.include_archived))
    if body.generation != matrix["generation"]:
        raise ToolError("stale: the skills changed since you looked; read skills_command_center again")
    col = next((c for c in matrix["columns"] if c["column_id"] == body.column_id), None)
    hit = next(((r, c) for r in matrix["rows"] for c in r["cells"].get(body.column_id, []) if c["location_id"] == body.location_id), None)
    if col is None or hit is None:
        raise ToolError("unknown or stale skill location")
    q = json.dumps
    summary = (f"move the local skill {q(hit[0]['name'][:120])} (folder {q(hit[1]['folder'][:120])}) out of "
               f"{q(col['label'][:80])} ({col['scope']}, {col['harness']}) into that skills folder's trash. It is not deleted.")

    async def run(approved: bool) -> dict:
        return _ok(await _via_route(routes.post_remove(_request(manager), body)))

    return await park(manager, caller, "", "", "skill_remove", summary, args, run,
                      dedupe_key=f"skill_remove:{body.column_id}:{body.location_id}", beast_eligible=False)


_COPY_PROPS = {
    "source_location_id": {"type": "string", "description": "a cell's location_id from skills_command_center"},
    "source_column_id": {"type": "string", "description": "the column_id that cell sits in"},
    "targets": {"type": "array", "minItems": 1, "maxItems": 50, "items": {
        "type": "object", "properties": {"column_id": {"type": "string"}, "replace": {"type": "boolean"}}, "required": ["column_id"]}},
    "dry_run": {"type": "boolean", "description": "default true: plan only, write nothing"},
    "generation": {"type": "string", "description": "from the dry run; required for a real copy"},
    "source_digest": {"type": "string", "description": "source.source_digest from the dry run; required for a real copy"},
    "include_archived": {"type": "boolean"},
}

WRITE_TOOLS: dict = {
    "skill_copy": ("Copy one local skill folder from one project (or a personal skills folder) into other projects or the personal "
                   "folders (claude ~/.claude/skills shared by every login, codex ~/.agents/skills). Dry run by default (digest, "
                   "scripts list); a real copy needs that dry run's generation and source_digest and waits for the owner's approval. "
                   "A replaced folder goes to the trash.",
                   _COPY_PROPS, ["source_location_id", "source_column_id", "targets"], skill_copy),
}

WRITE_TOOLS["skill_remove"] = (
    "Move one local skill folder out of a project (or a personal skills folder) into that folder's trash, never a delete. "
    "Needs a cell's location_id, its column_id and the generation from skills_command_center, and waits for the owner's "
    "approval. A catalog-installed copy is refused: uninstall it from the catalog.",
    {"location_id": {"type": "string"}, "column_id": {"type": "string"}, "generation": {"type": "string"},
     "include_archived": {"type": "boolean"}},
    ["location_id", "column_id", "generation"], skill_remove)

READ_TOOLS: dict = {
    "skills_command_center": ("Every locally installed skill against every non-archived project and the personal skills folders "
                              "(claude ~/.claude/skills, codex ~/.agents/skills): columns, rows by skill name, cell states "
                              "(present, differs, absent, none_yet, shadowed) and a generation stamp.",
                              {"include_archived": {"type": "boolean"}}, [], skills_command_center),
}
