
from __future__ import annotations

import asyncio
from typing import Any, Dict

from pydantic import ValidationError

from src.cplugs.reviewboard import live, mcp, wire
from src.cplugs.reviewboard.errors import BoardError
from src.cplugs.reviewboard.live_requests import LiveBody, LiveCreateBody, LiveEndBody, MilestoneBody
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result

_BOARD = {"type": "string", "description": "The board slug from task_manager_boards_list."}
_REQUEST_REVIEW = {"type": "boolean", "description": "Default true: the task goes to review so it reaches Joe. false: post the card only."}


def _slug(args: Dict[str, Any]) -> str:
    slug = args.get("board")
    if not isinstance(slug, str) or not slug:
        raise ToolError("board is required: a slug from task_manager_boards_list")
    return slug


async def task_manager_board_live_set(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    args = dict(args)
    cross = bool(args.pop(mcp.CROSS_PROJECT, False))
    slug = args.pop("board", None)
    creating = slug is None
    if creating:
        if "name" in args:
            args["slug_name"] = args.pop("name")
        if isinstance(args.get("task"), int) and not isinstance(args["task"], bool):
            args["task"] = {"item_id": args["task"]}
    elif not isinstance(slug, str) or not slug:
        raise ToolError("board must be a slug from task_manager_boards_list (leave it out to create a board that starts live)")
    args = await asyncio.to_thread(mcp.file_pages, args, caller)
    try:
        body = LiveCreateBody.model_validate(args) if creating else LiveBody.model_validate(args)
    except ValidationError as exc:
        raise mcp.refusal_for(exc) from exc
    try:
        answer = await (live.start_board(ctx, body, caller, cross) if creating else live.set_draft(ctx, slug, body, caller, cross))  # type: ignore[arg-type]
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    return tool_result(scrub(answer))


async def task_manager_board_milestone_add(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    args = dict(args)
    cross = bool(args.pop(mcp.CROSS_PROJECT, False))
    slug = _slug(args)
    args.pop("board")
    try:
        body = MilestoneBody.model_validate(args)
    except ValidationError as exc:
        raise mcp.refusal_for(exc) from exc
    try:
        answer = await live.milestone(ctx, slug, body, caller, cross)
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    return tool_result(scrub(answer))


async def task_manager_board_live_stop(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    args = dict(args)
    cross = bool(args.pop(mcp.CROSS_PROJECT, False))
    slug = _slug(args)
    args.pop("board")
    try:
        body = LiveEndBody.model_validate(args)
    except ValidationError as exc:
        raise mcp.refusal_for(exc) from exc
    try:
        answer = await live.end(ctx, slug, body, caller, cross)
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    return tool_result(scrub(answer))


_CROSS = {"type": "boolean", "description": "Only to write on a task of ANOTHER project's list (refused by default)."}

TOOLS: Dict[str, Any] = {
    "task_manager_board_live_set": ToolSpec(
        description=("Run a review board as a LIVE session: each call OVERWRITES the board's one working draft (no new revision, no card, the task's state "
                     "stays put), and the board Joe has open follows the draft as it changes (pushed). Use it for a demo or a back-and-forth. The first call "
                     "starts the session and puts the board on Joe's screen. Pass board (a slug) to go live on an existing board, or leave board out and "
                     "pass name, title, task and viewport to create a board that starts live with no revision at all. Same page rules as a revision "
                     "(docs/reviewboard.md): summary, html or file_path, viewport, views, prompts, anchors, max_width, inline_picks. No layer, no payload page. "
                     "When Joe sends from the board your session is woken directly with his answers (read them in task_manager_board_get, sidecar.live.sends). "
                     "Freeze the draft with task_manager_board_milestone_add when Joe says \"bookmark that\"; end with task_manager_board_live_stop."),
        properties={"board": {**_BOARD, "description": "The board slug; leave out to create a board that starts live (then name, title, task, viewport are required)."},
                    "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,47}$", "description": "Creating only: lowercase words joined by hyphens; the board is dated today."},
                    "title": {"type": "string", "minLength": 1, "maxLength": 120, "description": "Creating only: the board's title."},
                    "kind": {"type": "string", "enum": ["mockup", "flowchart", "copy", "other"], "description": "Creating only. Default mockup."},
                    "task": {"type": "integer", "minimum": 1, "description": "Creating only: the task manager item id (on this computer) the board belongs to."},
                    "summary": mcp.REVISION_PROPERTIES["summary"], "html": mcp.REVISION_PROPERTIES["html"], "file_path": mcp.REVISION_PROPERTIES["file_path"],
                    "viewport": mcp.REVISION_PROPERTIES["viewport"], "views": mcp.VIEWS, "prompts": mcp.PROMPTS, "anchors": mcp.ANCHORS,
                    "max_width": mcp.REVISION_PROPERTIES["max_width"], "inline_picks": mcp.REVISION_PROPERTIES["inline_picks"],
                    "open": {"type": "boolean", "description": "Default true: the call that STARTS the session puts the board on Joe's screen."},
                    **mcp.LOOK, mcp.CROSS_PROJECT: _CROSS},
        required=["summary"], handler=task_manager_board_live_set, gate="agent", pane_only_args=mcp.PANE_ONLY),
    "task_manager_board_milestone_add": ToolSpec(
        description=("Bookmark the live board's working draft: freeze it as a named revision, like a git commit. Only milestones are kept on disk. Call it when "
                     "Joe says \"bookmark that\" (or any such words). By default the task goes to review with the milestone's card (a milestone hands the "
                     "task to review). The session goes on; the draft stays as it is. Asking again with nothing changed adds nothing."),
        properties={"board": _BOARD, "name": {"type": "string", "minLength": 1, "maxLength": 120, "description": "The milestone's name; default \"milestone <n>\"."},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "Default: the draft's summary."},
                    "request_review": _REQUEST_REVIEW,
                    "base_etag": {"type": "string", "description": "The etag you read; a different current etag refuses the write."}, mcp.CROSS_PROJECT: _CROSS},
        required=["board"], handler=task_manager_board_milestone_add, gate="agent"),
    "task_manager_board_live_stop": ToolSpec(
        description=("End a board's live session: the working draft and its page files are dropped (name a milestone to freeze the draft first, so nothing is "
                     "lost) and the task goes to review with the newest revision's card. The board stays, with its milestones as revisions."),
        properties={"board": _BOARD, "milestone": {"type": "string", "minLength": 1, "maxLength": 120, "description": "Freeze the draft under this name before ending."},
                    "request_review": _REQUEST_REVIEW, mcp.CROSS_PROJECT: _CROSS},
        required=["board"], handler=task_manager_board_live_stop, gate="agent"),
}
