
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from src.cplugs.devwidgetlab.drafts import files, preview, service
from src.cplugs.devwidgetlab.errors import LabError
from src.cplugs.sdk import CplugContext, add_public_get


class DraftBody(BaseModel):
    """``POST /drafts``: a new widget (name, what it shows, hosts, sizes, category) or a revision (widget, what should change, what was on show)."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["new", "revision"]
    widget: str = Field(default="", max_length=80, pattern=r"^(|[a-z0-9][a-z0-9._:-]{0,79})$")
    name: str = Field(default="", max_length=80)
    what: str = Field(default="", max_length=4000)
    hosts: List[Literal["home", "terminal", "drawer", "popout"]] = ["home", "terminal"]
    sizes: List[Literal["small", "wide", "tall", "medium", "large", "full"]] = ["small", "wide"]
    category: Literal["overview", "sessions", "catalog", "monitoring", "tools", "live"] = "tools"
    context: Dict[str, str] = Field(default_factory=dict, max_length=20)


class FileBody(BaseModel):
    """``PUT /drafts/{slug}/file``: a path inside the draft folder and the text to write."""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=files.MAX_BYTES)


def _http(exc: LabError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": str(exc)})


def register(router: APIRouter, ctx_dep: Any) -> None:

    async def guarded(call: Callable[[], Any]) -> Any:
        try:
            return await asyncio.to_thread(call)
        except LabError as exc:
            raise _http(exc) from exc

    def storage(ctx: CplugContext) -> Path:
        return Path(ctx.storage.path)

    @router.get("/drafts")
    async def list_drafts(ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Every draft and whether drafts work here. Output: {available, reason, building, drafts}."""
        return await guarded(lambda: service.list_drafts(storage(ctx)))

    @router.post("/drafts")
    async def post_draft(body: DraftBody, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Make a draft folder. Output: its summary. Errors: 400, 409, 503."""
        return await guarded(lambda: service.create_draft(storage(ctx), body.model_dump()))

    @router.get("/drafts/{slug}")
    async def get_draft(slug: str, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """One draft's summary. Errors: 400, 404, 503."""
        return await guarded(lambda: service.get_draft(storage(ctx), slug))

    @router.post("/drafts/{slug}/build")
    async def post_build(slug: str, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Start the draft's preview build. Output: the summary (state ``building``). Errors: 404, 409 (a build is running), 503."""
        try:
            return service.build_draft(storage(ctx), slug)
        except LabError as exc:
            raise _http(exc) from exc

    @router.post("/drafts/{slug}/ticket")
    async def post_ticket(slug: str, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """A signed link to the built page; a stale build is rebuilt (``service.open_page``). Output: {path, expires_in, rebuild}. Errors: 400, 404 (nothing built yet), 503."""
        try:
            return await service.open_page(storage(ctx), slug)
        except LabError as exc:
            raise _http(exc) from exc

    @router.post("/drafts/{slug}/hand-to-claude")
    async def post_hand(slug: str, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Start a Claude session working in the folder. Output: the summary. Errors: 404, 502 (the create route refused), 503."""
        try:
            return await service.hand_to_claude(ctx, storage(ctx), slug)
        except LabError as exc:
            raise _http(exc) from exc

    @router.get("/drafts/{slug}/ship-plan")
    async def get_ship_plan(slug: str, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """The dry run of shipping this draft (writes nothing). Errors: 404, 503."""
        return await guarded(lambda: service.ship_plan(storage(ctx), slug))

    @router.get("/drafts/{slug}/files")
    async def get_files(slug: str, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Every file in the draft folder. Output: {slug, files}. Errors: 404, 503."""
        return await guarded(lambda: service.files_list(storage(ctx), slug))

    @router.get("/drafts/{slug}/file")
    async def get_file(slug: str, path: str = Query(min_length=1, max_length=300), ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """One text file of the draft. Output: {path, content, bytes}. Errors: 400 (outside the folder), 404, 503."""
        return await guarded(lambda: service.file_get(storage(ctx), slug, path))

    @router.put("/drafts/{slug}/file")
    async def put_file(slug: str, body: FileBody, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Write a text file inside the draft folder. Output: {path, bytes, created}. Errors: 400 (outside the folder, not writable, too large), 404, 503."""
        return await guarded(lambda: service.file_set(storage(ctx), slug, body.path, body.content))

    @router.delete("/drafts/{slug}/file")
    async def delete_file(slug: str, path: str = Query(min_length=1, max_length=300), ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Delete one file of the draft. Output: {path, deleted}. Errors: 400, 404, 503."""
        return await guarded(lambda: service.file_delete(storage(ctx), slug, path))

    @router.delete("/drafts/{slug}")
    async def delete_draft(slug: str, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Set the draft aside inside the Lab's storage. Output: {discarded}. Errors: 404, 503."""
        return await guarded(lambda: service.discard_draft(storage(ctx), slug))

    async def draft_harness(ticket: str, rel: str, ctx: CplugContext = ctx_dep) -> FileResponse:
        try:
            target = await asyncio.to_thread(preview.resolve_file, storage(ctx), ticket, rel)
        except LabError as exc:
            raise _http(exc) from exc
        return FileResponse(target, media_type=preview.media_type(target), headers={"Cache-Control": "no-cache"})

    add_public_get(router, "devwidgetlab", "/draft-harness/{ticket}/{rel:path}", draft_harness,
                   "an iframe cannot send a bearer; the signed ticket in the path is the credential (same origin framing, source checkout only)")
