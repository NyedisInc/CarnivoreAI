
from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any, Dict, List, Tuple

from src.cplugs.reviewboard import scratch, service, wire
from src.cplugs.reviewboard.errors import BoardError, NotScratch, TooLarge
from src.cplugs.reviewboard.mcp import CROSS_PROJECT
from src.cplugs.reviewboard.schema import MAX_VIEW_BYTES
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result
from src.cplugs.sdk.html_files import read_html_file
from src.cplugs.sdk.local_files import read_local_file

POST_ARGS = frozenset({"name", "title", "summary", "viewport", "html", "file_path", "files", "file_paths", CROSS_PROJECT})
PANE_ONLY = ("file_path", "file_paths")


def _inline_files(value: Any) -> List[scratch.Upload]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolError("files must be a list of {name, content_base64}")
    if len(value) > scratch.MAX_FILES:
        raise wire.tool_error(TooLarge(f"a scratch post carries at most {scratch.MAX_FILES} files, not {len(value)}"))
    if sum(len(e.get("content_base64") or "") for e in value if isinstance(e, dict)) * 3 // 4 > scratch.MAX_TOTAL_BYTES + 3 * len(value):
        raise wire.tool_error(TooLarge(f"a scratch post carries at most {scratch.MAX_TOTAL_BYTES // (1024 * 1024)} MB of files"))
    out = []
    for i, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != {"name", "content_base64"} or not isinstance(entry["content_base64"], str):
            raise ToolError(f"files[{i}] must be {{name, content_base64}}")
        try:
            data = base64.b64decode(entry["content_base64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError(f"files[{i}].content_base64 is not base64") from exc
        out.append(scratch.Upload(entry["name"] if isinstance(entry["name"], str) else "", data))
    return out


def _local_files(caller: AgentCaller, value: Any) -> List[scratch.Upload]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > scratch.MAX_FILES:
        raise ToolError(f"file_paths must be a list of at most {scratch.MAX_FILES} absolute paths")
    out = []
    total = 0
    for path in value:
        data, name = read_local_file(caller, path, argument="file_paths")
        total += len(data)
        if total > scratch.MAX_TOTAL_BYTES:
            raise wire.tool_error(TooLarge(f"a scratch post carries at most {scratch.MAX_TOTAL_BYTES // (1024 * 1024)} MB of files"))
        out.append(scratch.Upload(name, data))
    return out


def _request(caller: AgentCaller, args: Dict[str, Any]) -> Tuple[scratch.ScratchPost, bool]:
    unknown = sorted(set(args) - POST_ARGS)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    if ("html" in args) == ("file_path" in args):
        raise ToolError("pass exactly one of html (the page text) or file_path (an absolute path to an .html file, a session here only)")
    if "file_path" in args:
        if caller.from_token:
            raise ToolError("file_path names a file on this computer, so only a session running here may pass it; send html instead")
        html = read_html_file(args["file_path"], MAX_VIEW_BYTES)
    else:
        html = args["html"]
    files = _inline_files(args.get("files")) + _local_files(caller, args.get("file_paths"))
    name, viewport = args.get("name"), args.get("viewport")
    if not isinstance(name, str) or not isinstance(html, str):
        raise ToolError("name and html must be text")
    if viewport is not None and (isinstance(viewport, bool) or not isinstance(viewport, int)):
        raise ToolError("viewport must be a width in CSS px")
    request = scratch.ScratchPost(name=name, html=html, title=args.get("title"), summary=args.get("summary"), viewport=viewport, files=files)
    return request, bool(args.get(CROSS_PROJECT, False))


async def task_manager_scratch_post(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    try:
        request, cross = await asyncio.to_thread(_request, caller, dict(args))
        answer = await scratch.post(ctx, request, caller, cross)
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    return tool_result(scrub(answer))


async def _clear_prepare(ctx: CplugContext, caller: AgentCaller, args: dict) -> Tuple[dict, str]:
    slug = args.get("board")
    if set(args) - {"board"} or not isinstance(slug, str) or not slug:
        raise ToolError("board is required (a scratch board's slug from task_manager_boards_list), and nothing else")
    try:
        found = await asyncio.to_thread(service.board, wire.board_root(ctx), slug)
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    sidecar = found.get("sidecar")
    if not isinstance(sidecar, dict) or "scratch" not in (sidecar.get("ext") or {}):
        raise wire.tool_error(NotScratch(f"{slug} is not a scratch board; only a scratch board is cleared"))
    posts = len(sidecar.get("revisions") or [])
    return {"board": slug}, f"clear scratch board {slug} for good: {posts} post{'' if posts == 1 else 's'}, every page and file"


async def task_manager_scratch_clear(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    try:
        return tool_result(scrub(await scratch.clear(ctx, args["board"])))
    except BoardError as exc:
        raise wire.tool_error(exc) from exc


TOOLS: Dict[str, Any] = {
    "task_manager_scratch_post": ToolSpec(
        description=("Post a page and its files (images first of all) to a SCRATCH board, a temporary review board the owner reads in the Task "
                     "Manager: one call is one revision. name picks the board: the first post files a Scratch task and creates the board, "
                     "every later post with that name adds the next revision. The page is one self-contained HTML document; it shows a file "
                     "by naming it files/<name> (<img src=\"files/shot.png\">), and the server puts the file in. Files: files (each "
                     "{name, content_base64}) or, for a session running on this computer only, file_paths (absolute paths). At most "
                     f"{scratch.MAX_FILES} files, {scratch.MAX_TOTAL_BYTES // (1024 * 1024)} MB in all, an image 10 MB (png, jpg, gif, webp, "
                     "checked), the page 2 MB. Needs no approval: runs at once. It never moves the task; the card marks it unread."),
        properties={"name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,47}$", "description": "The scratch board: lowercase words joined by hyphens (phone, demo-1)."},
                    "title": {"type": "string", "minLength": 1, "maxLength": 120, "description": "A new board's title (default the name)."},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "One line on this post (default: scratch post)."},
                    "viewport": {"type": "integer", "minimum": 240, "maximum": 2560, "description": "The design width in CSS px (a phone page 390; default 1024, later posts keep the last)."},
                    "html": {"type": "string", "description": "The page. Or file_path."},
                    "file_path": {"type": "string", "description": "Instead of html: an ABSOLUTE .html path (a session running on this computer only)."},
                    "files": {"type": "array", "maxItems": scratch.MAX_FILES, "description": "Files inline.", "items": {
                        "type": "object", "required": ["name", "content_base64"], "additionalProperties": False,
                        "properties": {"name": {"type": "string", "description": "A plain file name (dog.jpg): letters, digits . _ -, no path."},
                                       "content_base64": {"type": "string", "description": "The file's bytes, base64."}}}},
                    "file_paths": {"type": "array", "maxItems": scratch.MAX_FILES, "items": {"type": "string"},
                                   "description": "Files by ABSOLUTE path on this computer (a session running here only; refused for a token)."},
                    CROSS_PROJECT: {"type": "boolean", "description": "Only to add to a scratch board on ANOTHER project's list."}},
        required=["name"], handler=task_manager_scratch_post, gate="agent_direct",
        max_body_bytes=scratch.MAX_BODY_BYTES, pane_only_args=PANE_ONLY),
    "task_manager_scratch_clear": ToolSpec(
        description=("Ask the owner to clear a scratch board for good: its folder, every post's page and files. It waits for his approval every "
                     "time, Beast Mode included (only the owner deletes). Only a scratch board is cleared; its Scratch task stays."),
        properties={"board": {"type": "string", "description": "The scratch board's slug from task_manager_boards_list (scratch: true)."}},
        required=["board"], handler=task_manager_scratch_clear, gate="inbox", prepare=_clear_prepare, dedupe_by=("board",)),
}
