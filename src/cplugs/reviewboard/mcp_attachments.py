
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from src.cplugs.reviewboard import attachment_removal, attachments, wire
from src.cplugs.reviewboard.errors import BoardError, TooLarge
from src.cplugs.reviewboard.mcp import CROSS_PROJECT
from src.cplugs.reviewboard.scratch import Upload
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result
from src.cplugs.sdk.local_files import read_local_file

NAME = "task_manager_board_attachment_add"
ARGS = frozenset({"board", "files", "file_paths", "note", "request_review", CROSS_PROJECT})
PANE_ONLY = ("file_paths",)


def _local_files(caller: AgentCaller, value: Any) -> List[Upload]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > attachments.MAX_FILES:
        raise ToolError(f"file_paths must be a list of at most {attachments.MAX_FILES} absolute paths")
    out = []
    total = 0
    for path in value:
        data, name = read_local_file(caller, path, argument="file_paths")
        total += len(data)
        if total > attachments.MAX_TOTAL_BYTES:
            raise TooLarge(f"an attach carries at most {attachments.MAX_TOTAL_BYTES // (1024 * 1024)} MB of files")
        out.append(Upload(name, data))
    return out


def _uploads(caller: AgentCaller, args: Dict[str, Any]) -> List[Upload]:
    unknown = sorted(set(args) - ARGS)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    if not isinstance(args.get("board"), str) or not args["board"]:
        raise ToolError("board is required: a slug from task_manager_boards_list")
    for flag in ("request_review", CROSS_PROJECT):
        if flag in args and not isinstance(args[flag], bool):
            raise ToolError(f"{flag} must be true or false")
    if args.get("note") is not None and not isinstance(args["note"], str):
        raise ToolError("note must be text")
    uploads = attachments.decode_inline(args.get("files")) + _local_files(caller, args.get("file_paths"))
    if len(uploads) > attachments.MAX_FILES:
        raise TooLarge(f"an attach carries at most {attachments.MAX_FILES} files, not {len(uploads)}")
    return uploads


async def task_manager_board_attachment_add(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    try:
        uploads = await asyncio.to_thread(_uploads, caller, dict(args))
        answer = await attachments.attach(ctx, args["board"], uploads, note=args.get("note"), request_review=args.get("request_review", True),
                                          caller=caller, cross_project=bool(args.get(CROSS_PROJECT, False)))
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    return tool_result(scrub(answer))


REMOVE_NAME = "task_manager_board_attachment_remove"
REMOVE_ARGS = frozenset({"board", "file_id", CROSS_PROJECT})


async def task_manager_board_attachment_remove(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    unknown = sorted(set(args) - REMOVE_ARGS)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    for key in ("board", "file_id"):
        if not isinstance(args.get(key), str) or not args[key]:
            raise ToolError(f"{key} is required" + (": a slug from task_manager_boards_list" if key == "board" else ": the file_id from the board's attachments"))
    if CROSS_PROJECT in args and not isinstance(args[CROSS_PROJECT], bool):
        raise ToolError(f"{CROSS_PROJECT} must be true or false")
    try:
        answer = await attachment_removal.remove(ctx, args["board"], args["file_id"], caller=caller, cross_project=bool(args.get(CROSS_PROJECT, False)))
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    return tool_result(scrub(answer))


TOOLS: Dict[str, Any] = {
    NAME: ToolSpec(
        description=("Attach files to a review board (a spec, a PDF, a screenshot, notes): each file is stored as the board's task's own file "
                     "and shows on the task's thread in one info naming them, and the board lists it under its paperclip. Files: files "
                     "(each {name, content_base64}) or, for a session running on this computer only, file_paths (absolute paths); at most "
                     f"{attachments.MAX_FILES} in all, {attachments.MAX_TOTAL_BYTES // (1024 * 1024)} MB together, an image 10 MB (png, jpg, "
                     "gif, webp, checked), any other file 50 MB. By default the task goes to review, as a revision does. A scratch board "
                     "takes its files with task_manager_scratch_post instead."),
        properties={"board": {"type": "string", "description": "The board slug from task_manager_boards_list."},
                    "files": {"type": "array", "maxItems": attachments.MAX_FILES, "description": "Files inline.", "items": {
                        "type": "object", "required": ["name", "content_base64"], "additionalProperties": False,
                        "properties": {"name": {"type": "string", "description": "The file name (spec.pdf); a path is reduced to its name."},
                                       "content_base64": {"type": "string", "description": "The file's bytes, base64."}}}},
                    "file_paths": {"type": "array", "maxItems": attachments.MAX_FILES, "items": {"type": "string"},
                                   "description": "Files by ABSOLUTE path on this computer (a session running here only; refused for a token)."},
                    "note": {"type": "string", "maxLength": attachments.MAX_NOTE, "description": "A line or two for the task's thread."},
                    "request_review": {"type": "boolean", "description": "Default true: the task goes to review so it reaches Joe. false: post the info only."},
                    CROSS_PROJECT: {"type": "boolean", "description": "Only to attach on a task of ANOTHER project's list (refused by default)."}},
        required=["board"], handler=task_manager_board_attachment_add, gate="agent",
        max_body_bytes=attachments.MAX_BODY_BYTES, pane_only_args=PANE_ONLY),
    REMOVE_NAME: ToolSpec(
        description=("Remove an attachment from a review board. This takes the file off the BOARD only: it stops showing under the paperclip and "
                     "the board keeps a removed entry in its index (name, size, sha256, when) for the history. The file is deleted from the Task Manager too: its bytes "
                     "go and the task's thread line says it was removed, unless another message on the task still carries the same file. Only the agent that attached the file (or the owner) may remove it; any other agent is refused 403 reviewboard_not_attacher. Get the file_id from the board's attachments list."),
        properties={"board": {"type": "string", "description": "The board slug from task_manager_boards_list."},
                    "file_id": {"type": "string", "description": "The attachment's file_id (8 hex characters)."},
                    CROSS_PROJECT: {"type": "boolean", "description": "Only to remove on a task of ANOTHER project's list (refused by default)."}},
        required=["board", "file_id"], handler=task_manager_board_attachment_remove, gate="agent"),
}
