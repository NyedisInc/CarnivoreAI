
from __future__ import annotations

import asyncio
from typing import Any

from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _TARGET_SCHEMA, ToolError, _local_infos, _ok, _resolve
from src.core.mcp.write_tools import _request, _session_uuid_of_row, _via_route, park

MAX_LISTED = 50
_BOOKMARK_ID = {"type": "integer", "minimum": 1, "description": "An id from bookmarks_list."}


async def _session_uuid(manager: Any, args: dict) -> str:
    info = _resolve(await _local_infos(manager), args)
    if info.session_row_id is None:
        raise ToolError("no stored row for that session")
    found = await asyncio.to_thread(_session_uuid_of_row, info.session_row_id)
    if found is None:
        raise ToolError("no stored row for that session")
    return found


def _bookmark_id(args: dict) -> int:
    value = args.get("bookmark")
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolError("bookmark is required: an id from bookmarks_list")
    return value


async def bookmark_add(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_bookmark_routes as routes
    from src.models.bookmarks import AddBookmarkRequest

    label = args.get("label")
    if not isinstance(label, str) or not label.strip() or len(label) > 200:
        raise ToolError("label is required text of at most 200 characters")
    session_uuid = await _session_uuid(manager, args)
    made = await _via_route(routes.add_bookmark(session_uuid, AddBookmarkRequest(
        label=label.strip(), point="now", created_by="claude")))
    return _ok(made.model_dump())


async def bookmarks_list(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_bookmark_routes as routes

    listed = await _via_route(routes.list_bookmarks(await _session_uuid(manager, args)))
    marks = [{k: b[k] for k in ("id", "label", "created_by", "created_at", "snippet", "claude_session_uuid")}
             for b in listed.model_dump()["bookmarks"]]
    return _ok({"conversation": listed.conversation, "bookmarks": marks[:MAX_LISTED],
                "truncated": len(marks) > MAX_LISTED})


async def bookmark_branch(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_bookmark_routes as routes

    bookmark_id = _bookmark_id(args)
    mark = await _via_route(routes._bookmark(bookmark_id))

    async def run(approved: bool) -> dict:
        made = await _via_route(routes.branch_bookmark(_request(manager), bookmark_id))
        return _ok({"label": made.label, "claude_session_uuid": made.claude_session_uuid,
                    "session_id": made.session.get("id"), "lineage_recorded": made.lineage_recorded})

    summary = f"open a new session from the bookmark {mark.label or mark.snippet[:60]!r} (id {bookmark_id}, a copy cut there; the original is untouched)"
    return await park(manager, caller, "", "", "bookmark_branch", summary, {"bookmark": bookmark_id}, run,
                      dedupe_key=f"bookmark_branch:{bookmark_id}")


async def bookmark_rewind(manager: Any, caller: AgentCaller, args: dict) -> dict:
    from src.api import session_bookmark_routes as routes
    from src.models.bookmarks import ConfirmRequest

    bookmark_id = _bookmark_id(args)
    if args.get("confirm") is not True:
        raise ToolError("confirm must be true: a rewind kills what the pane is running and resumes the cut copy")
    mark = await _via_route(routes._bookmark(bookmark_id))

    async def run(approved: bool) -> dict:
        done = await _via_route(routes.rewind_bookmark(_request(manager), bookmark_id, ConfirmRequest(confirm=True)))
        return _ok(done.model_dump())

    summary = (f"REWIND IN PLACE to bookmark {bookmark_id} ({mark.label or mark.snippet[:60]!r}): kills what the pane "
               "is running and resumes a cut copy; the full transcript stays on disk")
    return await park(manager, caller, "", "", "bookmark_rewind", summary, {"bookmark": bookmark_id, "confirm": True},
                      run, dedupe_key=f"bookmark_rewind:{bookmark_id}", beast_eligible=False)


READ_TOOLS: dict = {
    "bookmarks_list": (
        "A session's bookmarks, newest first (id, label, who made it, the prompt it marks).",
        {"target": _TARGET_SCHEMA}, ["target"], bookmarks_list,
    ),
}

WRITE_TOOLS: dict = {
    "bookmark_add": (
        "Bookmark where a Claude Code session's conversation stands now, with a label, for example before a risky "
        "change. Runs at once; the owner can later branch from it or rewind to it.",
        {"target": _TARGET_SCHEMA, "label": {"type": "string", "maxLength": 200}}, ["target", "label"], bookmark_add,
    ),
    "bookmark_branch": (
        "Open a NEW session on a copy of the conversation cut at a bookmark. The original session and transcript "
        "are untouched. Asks the owner unless Beast Mode is armed.",
        {"bookmark": _BOOKMARK_ID}, ["bookmark"], bookmark_branch,
    ),
    "bookmark_rewind": (
        "Rewind a bookmark's own session in place: kill what its pane runs and resume a copy cut at the bookmark. "
        "The full transcript stays on disk. Needs confirm: true and always waits for the owner's approval.",
        {"bookmark": _BOOKMARK_ID, "confirm": {"type": "boolean"}}, ["bookmark", "confirm"], bookmark_rewind,
    ),
}

UNGATED_WRITES = frozenset({"bookmark_add"})
