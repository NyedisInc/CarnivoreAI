
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict

from pydantic import ValidationError

from src.cplugs.reviewboard import opener, publish, service, wire
from src.cplugs.reviewboard import state as board_states
from src.cplugs.reviewboard.errors import BoardError
from src.cplugs.reviewboard.layers import tool_schema
from src.cplugs.reviewboard.requests import CreateBody, ReviseBody
from src.cplugs.reviewboard.schema import MAX_ANCHORS, MAX_OPTIONS, MAX_PROMPTS, MAX_VIEW_BYTES
from src.cplugs.sdk import browser_pages
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result
from src.cplugs.sdk.html_files import read_html_file

CROSS_PROJECT = "cross_project"


async def _blocking(call: Any) -> Any:
    try:
        return await asyncio.to_thread(call)
    except BoardError as exc:
        raise wire.tool_error(exc) from exc


async def task_manager_boards_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    task, state, project = args.get("task"), args.get("state"), args.get("project")
    if task is not None and (isinstance(task, bool) or not isinstance(task, int) or task < 1):
        raise ToolError("task must be an item id from task_manager_tasks_list")
    if state is not None and state not in board_states.STATES:
        raise ToolError("state is one of: " + ", ".join(board_states.STATES))
    if project is not None and (not isinstance(project, str) or not project or len(project) > service.MAX_PROJECT_KEY):
        raise ToolError("project is a project's list key, its id as digits (projects_list)")
    root = await _blocking(lambda: wire.board_root(ctx))
    try:
        answer = await service.listing(root, task, state, project)
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    return tool_result(scrub(answer))


async def task_manager_board_get(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug = args.get("board")
    since = args.get("since_round")
    saves = args.get("saves", "all")
    if not isinstance(slug, str) or not slug:
        raise ToolError("board is required: a slug from task_manager_boards_list")
    if saves not in service.SAVES_MODES:
        raise ToolError("saves is one of: " + ", ".join(service.SAVES_MODES))
    if since is not None and (isinstance(since, bool) or not isinstance(since, int) or since < 0):
        raise ToolError("since_round must be a round number (0 or more)")
    try:
        root = wire.board_root(ctx)
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    answer: Dict[str, Any] = await _blocking(lambda: service.board(root, slug))
    if since is not None:
        answer = service.rounds_after(answer, since)
    return tool_result(scrub(service.with_saves(answer, saves)))


PANE_ONLY = ("file_path",)


def refuse_token_paths(caller: AgentCaller, args: Dict[str, Any]) -> None:
    if not caller.from_token:
        return
    views = args.get("views")
    nested = isinstance(views, list) and any(isinstance(v, dict) and "file_path" in v for v in views)
    if "file_path" in args or nested:
        raise ToolError("file_path names a file on this computer, so only a session running here may pass it; send the page as html instead")


def file_pages(args: Dict[str, Any], caller: AgentCaller) -> Dict[str, Any]:
    refuse_token_paths(caller, args)
    def page(holder: Dict[str, Any], where: str) -> Dict[str, Any]:
        main = where == "the page"
        both, neither = "html" in holder and "file_path" in holder, "html" not in holder and "file_path" not in holder
        if both or (neither and not (main and tool_schema.allows_no_page(args))):
            raise ToolError(f"{where}: pass exactly one of html (the page text) or file_path (an absolute path to an .html file)"
                            + (", or leave both out with a questions layer" if main else ""))
        if "file_path" not in holder:
            return holder
        out = {k: v for k, v in holder.items() if k != "file_path"}
        out["html"] = read_html_file(holder["file_path"], MAX_VIEW_BYTES)
        return out

    out = page(dict(args), "the page")
    views = out.get("views")
    if isinstance(views, list):
        out["views"] = [page(dict(v), f"views[{i}]") if isinstance(v, dict) else v for i, v in enumerate(views)]
    return out


def refusal_for(exc: ValidationError) -> ToolError:
    shown = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors()[:5])
    return ToolError(f"refused (reviewboard_invalid): {shown}")


async def _write(ctx: CplugContext, caller: AgentCaller, args: dict, creating: bool) -> dict:
    args = dict(args)
    cross = bool(args.pop(CROSS_PROJECT, False))
    slug = args.pop("board", None)
    if creating:
        if "name" in args:
            args["slug_name"] = args.pop("name")
        if isinstance(args.get("task"), int) and not isinstance(args["task"], bool):
            args["task"] = {"item_id": args["task"]}
    elif not isinstance(slug, str) or not slug:
        raise ToolError("board is required: a slug from task_manager_boards_list")
    args = await asyncio.to_thread(file_pages, args, caller)
    try:
        body = CreateBody.model_validate(args) if creating else ReviseBody.model_validate(args)
    except ValidationError as exc:
        raise refusal_for(exc) from exc
    try:
        answer = await (publish.create_board(ctx, body, caller, cross) if creating else publish.add_revision(ctx, slug, body, caller, cross))
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    return tool_result(scrub(answer))


async def task_manager_board_create(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _write(ctx, caller, args, True)


async def task_manager_board_revision_add(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _write(ctx, caller, args, False)


async def task_manager_board_focus(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug, revision = args.get("board"), args.get("revision")
    if not isinstance(slug, str) or not slug:
        raise ToolError("board is required: a slug from task_manager_boards_list")
    if revision is not None and (not isinstance(revision, str) or not re.fullmatch(r"r[1-9][0-9]*", revision)):
        raise ToolError("revision is a revision id like r2")
    color, icon = args.get("color"), args.get("icon")
    try:
        browser_pages.check_look(color, icon)
    except browser_pages.RowLookRefused as exc:
        raise ToolError(str(exc)) from exc
    try:
        root = wire.board_root(ctx)
    except BoardError as exc:
        raise wire.tool_error(exc) from exc
    return tool_result(scrub(await _blocking(lambda: opener.open_board(root, slug, revision, color, icon))))


PROMPTS = {"type": "array", "maxItems": MAX_PROMPTS, "description": "What you want Joe to answer on this revision. Reuse an id to ask the same question again.", "items": {
    "type": "object", "required": ["id", "kind", "label"], "additionalProperties": False,
    "properties": {"id": {"type": "string", "description": "lowercase id, letters digits - _"},
                   "kind": {"type": "string", "enum": ["choice", "multi", "check", "question"], "description": "choice: one option; multi: any; check: one box; question: his words"},
                   "label": {"type": "string", "maxLength": 300},
                   "options": {"type": "array", "maxItems": MAX_OPTIONS, "description": "for choice and multi", "items": {
                       "type": "object", "required": ["id", "label"], "additionalProperties": False,
                       "properties": {"id": {"type": "string"}, "label": {"type": "string", "maxLength": 120}}}},
                   "anchor": {"type": "string", "description": "an anchor id this prompt is about"}}}}
ANCHORS = {"type": "array", "maxItems": MAX_ANCHORS, "description": "Named parts of the page Joe may point at; tag each in the HTML with data-rb-anchor=\"<id>\".", "items": {
    "type": "object", "required": ["id", "label"], "additionalProperties": False,
    "properties": {"id": {"type": "string"}, "label": {"type": "string", "maxLength": 120}}}}
VIEWS = {"type": "array", "maxItems": 6, "description": "More pages of the same revision (the main page is html or file_path).", "items": {
    "type": "object", "required": ["id", "label"], "additionalProperties": False,
    "properties": {"id": {"type": "string", "description": "not main"}, "label": {"type": "string", "maxLength": 120},
                   "html": {"type": "string"}, "file_path": {"type": "string", "description": "instead of html: an ABSOLUTE .html path"}}}}
REVISION_PROPERTIES: Dict[str, Any] = {
    "summary": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "One or two plain lines: what this revision is, or what changed since the last."},
    "html": {"type": "string", "description": "The page as one self-contained HTML document (up to 2 MB, inline CSS and JS, data: images, colors from var(--oc-*) with a :root fallback). Or file_path. Optional with a questions layer."},
    "file_path": {"type": "string", "description": "Instead of html: an ABSOLUTE path to an .html file you wrote (not a symlink)."},
    "viewport": {"type": "integer", "minimum": 240, "maximum": 2560, "description": "The design width in CSS px, stated truthfully (a sidebar mockup 300, a pop-out 520, a page 1400). Required for the first revision; later ones keep the last."},
    "views": VIEWS, "prompts": PROMPTS, "anchors": ANCHORS, "layer": tool_schema.LAYER,
    "inline_picks": {"type": "boolean", "description": "true: the board draws each prompt that names an anchor right under that anchored part of the page (the answers stay in Joe's tray, never in the page); prompts with no anchor stay in the tray's list. Tag each part with data-rb-anchor and list it in anchors, and give the prompt that anchor."},
    "max_width": {"type": "integer", "minimum": 480, "maximum": 2400, "description": "Optional, canvas pages only: hold the page to this width in CSS px, centered (480 to 2400). Leave it out for full width. Joe gets a key in the board bar to switch between this width and full width. Questions and rows layers have their own fixed width."},
    "answers_round": {"type": "string", "description": "The round (n1, n2, ...) of Joe's this revision answers; always name it when you are replying to one."},
    "source_commit": {"type": "string", "description": "The commit the mockup was built from, if any."},
    "payload_mode": {"type": "boolean", "description": "true: the page owns its controls and posts its state (rb payload message, docs/reviewboard.md, Payload pages). The board autosaves it as revision.draft and Joe's Send only nudges you to review it. No prompt list."},
    "request_review": {"type": "boolean", "description": "Default true: the task goes to review so it reaches Joe. false: post the card only."},
    CROSS_PROJECT: {"type": "boolean", "description": "Only to publish on a task of ANOTHER project's list (refused by default)."}}


LOOK: Dict[str, Any] = {
    "color": {"type": "string", "enum": list(browser_pages.COLORS), "description": "OPTIONAL sidebar row color, a theme color name"},
    "icon": {"type": "string", "enum": list(browser_pages.ICONS), "description": "OPTIONAL sidebar row icon name"}}

TOOLS: dict[str, Any] = {
    "task_manager_boards_list": ToolSpec(
        description=("List the review boards (mockups under review): slug, title, linked task, revisions, rounds Joe has sent, and the state "
                     "(your_turn: Joe has not answered the newest revision; with_claude: Joe's newest round waits for a revision; "
                     "undelivered: a round never reached its task; closed: its task is done, with closed_at and task_title). Each row names "
                     "its project (a list key). Newest activity first; state closed runs newest closed first. Filter by task, state, project. Read only."),
        properties={"task": {"type": "integer", "minimum": 1, "description": "Only boards linked to this task manager item id."},
                    "state": {"type": "string", "enum": list(board_states.STATES), "description": "Only boards in this state."},
                    "project": {"type": "string", "minLength": 1, "maxLength": service.MAX_PROJECT_KEY,
                                "description": "Only boards of this project: its list key (the project id as digits)."}},
        required=[], handler=task_manager_boards_list, gate="read"),
    "task_manager_board_get": ToolSpec(
        description=("Read one review board: sidecar (revisions with prompts and anchors; Joe's rounds), state, etag, revision_dir. "
                     "Never returns HTML. since_round returns only newer rounds. A payload page (payload_mode) shows numbered saves in "
                     "revision.saves, the autosaved working state in revision.draft, and Joe's sends as rounds with payload, save, diff; "
                     "saves narrows them (all, latest, none). A board running as a LIVE session shows sidecar.live: the working draft (seq, summary, views, prompts), who "
                     "opened it, and Joe's recent live sends (live.sends, newest last; read them here after the wake that told you). Read only."),
        properties={"board": {"type": "string", "description": "The board slug from task_manager_boards_list."},
                    "since_round": {"type": "integer", "minimum": 0, "description": "Only rounds numbered above this."},
                    "saves": {"type": "string", "enum": ["all", "latest", "none"], "description": "Payload saves per revision: all (default), only the newest, or none."}},
        required=["board"], handler=task_manager_board_get, gate="read"),
    "task_manager_board_create": ToolSpec(
        description=("Start a review board for a task: Joe reviews your mockup in rounds, ticking choices, checking boxes and writing notes on it, "
                     "and his send comes back to you on the task as his reply. Posts revision r1 (a page, a summary and the prompts you want answered) "
                     "into the boards folder and a card on the task, and by default puts the task in review. Revisions are immutable: change the "
                     "mockup with task_manager_board_revision_add. Read docs/reviewboard.md for the page contract. Optional color and icon style the "
                     "board's sidebar row when it is opened. Needs the boards folder set."),
        properties={"name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,47}$", "description": "Lowercase words joined by hyphens; the board is dated today."},
                    "title": {"type": "string", "minLength": 1, "maxLength": 120, "description": "The board's title."},
                    "kind": {"type": "string", "enum": ["mockup", "flowchart", "copy", "other"], "description": "Default mockup."},
                    "task": {"type": "integer", "minimum": 1, "description": "The task manager item id (on this computer) Joe's rounds go to."},
                    **LOOK, **REVISION_PROPERTIES},
        required=["name", "title", "task", "summary", "viewport"], handler=task_manager_board_create, gate="agent", pane_only_args=PANE_ONLY),
    "task_manager_board_revision_add": ToolSpec(
        description=("Add the next revision to a review board (the tool you use most): a new page, a summary, and the prompts for this round. Name "
                     "answers_round when you are answering one of Joe's rounds (read it first with task_manager_board_get). Posts the card on the "
                     "task and by default puts it in review. An older revision never changes. base_etag is optional: a revision only appends, but "
                     "pass the etag you read to refuse a write over a change you have not seen."),
        properties={"board": {"type": "string", "description": "The board slug from task_manager_boards_list."},
                    "base_etag": {"type": "string", "description": "The etag you read; a different current etag refuses the write."},
                    **REVISION_PROPERTIES},
        required=["board", "summary"], handler=task_manager_board_revision_add, gate="agent", pane_only_args=PANE_ONLY),
    "task_manager_board_focus": ToolSpec(
        description=("Open a review board on Joe's screen: a row in his browser list, shown full size in his center screen at that revision (or "
                     "the newest). Use it to point him at a revision you just posted. Optional color and icon style the row "
                     "(restyle later with sidebar_row_look_set). Changes only what is on his screen."),
        properties={"board": {"type": "string", "description": "The board slug from task_manager_boards_list."},
                    "revision": {"type": "string", "pattern": "^r[1-9][0-9]*$", "description": "A revision id like r2; leave out to follow the newest."},
                    **LOOK},
        required=["board"], handler=task_manager_board_focus, gate="agent"),
}
