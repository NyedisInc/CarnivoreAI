
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict

from pydantic import ValidationError

from src.cplugs.devwidgetlab.draft_routes import DraftBody
from src.cplugs.devwidgetlab.drafts import service
from src.cplugs.devwidgetlab.errors import LabError
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, scrub, tool_result

SLUG = {"type": "string", "description": "The draft's name (its folder), from widget_lab_drafts_list."}
PATH = {"type": "string", "description": "A path inside the draft folder, such as files/web/src/opscenter/cells/<name>/Cell.svelte."}


async def _run(ctx: CplugContext, call: Callable[[Path], Any], *, read: bool = False) -> dict:
    try:
        data = await asyncio.to_thread(call, Path(ctx.storage.path))
    except LabError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc
    return tool_result(scrub(data) if read else data)


def _slug(args: dict) -> str:
    slug = args.get("slug")
    if not isinstance(slug, str) or not slug:
        raise ToolError("refused (draft_invalid): slug is required")
    return slug


async def widget_lab_drafts_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    return await _run(ctx, service.list_drafts, read=True)


async def widget_lab_draft_get(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug = _slug(args)
    return await _run(ctx, lambda storage: service.get_draft(storage, slug), read=True)


async def widget_lab_draft_create(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    try:
        body = DraftBody.model_validate(args).model_dump()
    except ValidationError as exc:
        raise ToolError(f"refused (draft_invalid): {exc.errors()[0]['loc']}: {exc.errors()[0]['msg']}") from exc
    return await _run(ctx, lambda storage: service.create_draft(storage, body))


async def widget_lab_draft_files_list(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug = _slug(args)
    return await _run(ctx, lambda storage: service.files_list(storage, slug), read=True)


async def widget_lab_draft_file_get(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug, path = _slug(args), str(args.get("path", ""))
    return await _run(ctx, lambda storage: service.file_get(storage, slug, path), read=True)


async def widget_lab_draft_file_set(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug, path, content = _slug(args), str(args.get("path", "")), args.get("content")
    if not isinstance(content, str):
        raise ToolError("refused (draft_invalid): content must be text")
    return await _run(ctx, lambda storage: service.file_set(storage, slug, path, content))


async def widget_lab_draft_file_delete(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug, path = _slug(args), str(args.get("path", ""))
    return await _run(ctx, lambda storage: service.file_delete(storage, slug, path))


async def widget_lab_draft_rebuild(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug = _slug(args)
    try:
        return tool_result(await service.build_draft(Path(ctx.storage.path), slug))
    except LabError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc


async def widget_lab_draft_spawn(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug = _slug(args)
    try:
        return tool_result(await service.hand_to_claude(ctx, Path(ctx.storage.path), slug))
    except LabError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc


async def widget_lab_draft_delete(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    slug = _slug(args)
    return await _run(ctx, lambda storage: service.discard_draft(storage, slug))


TOOLS: Dict[str, ToolSpec] = {
    "widget_lab_drafts_list": ToolSpec(
        description="List the Widget Lab drafts (widget folders in the Lab's own storage): slug, kind (new or revision), widget id, state, changed files, last build. Read only.",
        properties={}, required=[], handler=widget_lab_drafts_list, gate="read"),
    "widget_lab_draft_get": ToolSpec(
        description="One Widget Lab draft: its record, changed files and last build. Read only.",
        properties={"slug": SLUG}, required=["slug"], handler=widget_lab_draft_get, gate="read"),
    "widget_lab_draft_create": ToolSpec(
        description=("Make a Widget Lab draft. kind new needs a name (the widget's title) and writes starter files (cell stub, fixtures, manifest entry, contract record, brief); "
                     "kind revision needs the widget id (such as core.notes) and writes a folder holding only the brief, so copy a repo file into files/ (same path) to change it. "
                     "Writes only inside the Lab's storage."),
        properties={"kind": {"type": "string", "enum": ["new", "revision"]}, "widget": {"type": "string", "description": "revision: the widget id."},
                    "name": {"type": "string", "description": "new: the widget's title; revision: a short name for the draft."},
                    "what": {"type": "string", "description": "new: what it shows; revision: what should change."},
                    "hosts": {"type": "array", "items": {"type": "string", "enum": ["home", "terminal", "drawer", "popout"]}, "description": "new only: every place the widget is drawn, the drawer and the pop-out window included. Default home and terminal."},
                    "sizes": {"type": "array", "items": {"type": "string", "enum": ["small", "wide", "tall", "medium", "large", "full"]}, "description": "new only. Default small and wide."},
                    "category": {"type": "string", "enum": ["overview", "sessions", "catalog", "monitoring", "tools", "live"]},
                    "context": {"type": "object", "additionalProperties": {"type": "string"}, "description": "revision: what was on show (theme, size, findings)."}},
        required=["kind", "name"], handler=widget_lab_draft_create, gate="agent"),
    "widget_lab_draft_files_list": ToolSpec(
        description="Every file in a Widget Lab draft folder (path and size). Read only.",
        properties={"slug": SLUG}, required=["slug"], handler=widget_lab_draft_files_list, gate="read"),
    "widget_lab_draft_file_get": ToolSpec(
        description="Read one text file of a Widget Lab draft folder (confined to the folder; no traversal, no symlinks). Read only.",
        properties={"slug": SLUG, "path": PATH}, required=["slug", "path"], handler=widget_lab_draft_file_get, gate="read"),
    "widget_lab_draft_file_set": ToolSpec(
        description=("Write one text file inside a Widget Lab draft folder: BRIEF.md, widget.json, contract.json, captures/..., or files/web/src/... (the draft's copy of a repo file; "
                     "the preview uses it in place of the real one). Confined to the folder; generated files are refused. Never touches the checkout."),
        properties={"slug": SLUG, "path": PATH, "content": {"type": "string", "description": "The whole file, UTF-8 text, at most 512 KB."}},
        required=["slug", "path", "content"], handler=widget_lab_draft_file_set, gate="agent"),
    "widget_lab_draft_file_delete": ToolSpec(
        description="Delete one file of a Widget Lab draft folder (a copy; the checkout is untouched). Same path rules as widget_lab_draft_file_set.",
        properties={"slug": SLUG, "path": PATH}, required=["slug", "path"], handler=widget_lab_draft_file_delete, gate="agent"),
    "widget_lab_draft_rebuild": ToolSpec(
        description="Build a Widget Lab draft's live preview so it shows in the Lab beside the current widget. One build at a time; answers at once with state building. Needs a source checkout (a source install, or developer mode on with the Lab's source checkout set).",
        properties={"slug": SLUG}, required=["slug"], handler=widget_lab_draft_rebuild, gate="agent"),
    "widget_lab_draft_spawn": ToolSpec(
        description="Hand a Widget Lab draft to Claude: start a Claude session working in the draft's folder from its BRIEF.md. Needs a source checkout (a source install, or developer mode on with the Lab's source checkout set). Nothing is shipped.",
        properties={"slug": SLUG}, required=["slug"], handler=widget_lab_draft_spawn, gate="agent"),
    "widget_lab_draft_delete": ToolSpec(
        description="Discard a Widget Lab draft: its folder is set aside inside the Lab's storage (not deleted). The owner's tick, not this tool, ships anything.",
        properties={"slug": SLUG}, required=["slug"], handler=widget_lab_draft_delete, gate="agent"),
}
