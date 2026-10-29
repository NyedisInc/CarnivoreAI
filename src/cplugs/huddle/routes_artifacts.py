
from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

from src.cplugs.huddle import artifact_post, artifact_ticket, artifacts, files, task_files
from src.cplugs.huddle.routes import Ctx, router, run_store
from src.cplugs.sdk import OWN_POLICY_HEADER, CplugContext, add_public_get

VIEW_PATH = f"/api/v1{router.prefix}/artifact-view"


class ArtifactRequest(BaseModel):
    """An artifact: a title, an optional one-line description and the whole page."""

    model_config = ConfigDict(extra="forbid")
    title: str
    description: str = ""
    html: str


@router.post("/items/{item_id}/artifacts")
async def post_artifact(item_id: int, body: ArtifactRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Post a page on the item's thread. Output: {item, message} (the message carries ``artifact``). Errors: 400, 404."""
    return await run_store(lambda: artifact_post.post(ctx, item_id, body.title, body.description, body.html))


@router.post("/items/{item_id}/artifacts/{file_id}/ticket")
async def artifact_ticket_for(item_id: int, file_id: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """A signed ticket and the viewer URL for one artifact page. Output: {url, expires_in, title}. Errors: 404 (not an artifact of this item)."""
    meta = await run_store(lambda: artifacts.find(ctx.storage, item_id, file_id))
    if meta is None:
        raise HTTPException(status_code=404, detail={"code": "task_manager_not_found", "detail": "no such artifact"})
    return {"url": viewer_path(item_id, file_id), "expires_in": artifact_ticket.TTL_S, "title": meta["title"]}


def viewer_path(item_id: int, file_id: str) -> str:
    return f"{VIEW_PATH}/{artifact_ticket.mint(item_id, file_id)}"


async def view_artifact(ticket: str, ctx: CplugContext = Ctx) -> Response:
    named = artifact_ticket.verify(ticket)
    if named is None:
        raise HTTPException(status_code=404, detail={"code": "task_manager_not_found", "detail": "no such artifact"})
    path = await run_store(lambda: files.locate(ctx.storage, named[0], named[1], task_files.search_dirs(named[0])))
    data = await run_store(path.read_bytes)
    return Response(content=data, media_type="text/html; charset=utf-8", headers={**artifacts.VIEW_HEADERS, OWN_POLICY_HEADER: "1"})


add_public_get(router, "huddle", "/artifact-view/{ticket}", view_artifact)
