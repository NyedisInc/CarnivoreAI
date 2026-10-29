
from __future__ import annotations

import asyncio
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field

from src.cplugs.reviewboard import opener, pages, wire
from src.cplugs.reviewboard.errors import BoardError, BoardNotFound
from src.cplugs.reviewboard.routes import Ctx, router
from src.cplugs.sdk import CplugContext


class PostedOpenBody(BaseModel):
    """Which posted page to open: the task and the title it was posted under."""

    model_config = ConfigDict(extra="forbid")
    item: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)


@router.post("/posted/open")
async def open_posted(body: PostedOpenBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Open the board of a posted page. Inputs: body {item, title}. Output: {page, select}. Errors: 404 (no such board), 409 (no boards folder)."""
    def open_it() -> Dict[str, Any]:
        root = wire.board_root(ctx)
        slug = pages.existing_board(root, body.item, body.title)
        if slug is None:
            raise BoardNotFound(f"task {body.item} has no board titled {body.title}")
        return opener.open_board(root, slug)

    try:
        return await asyncio.to_thread(open_it)
    except BoardError as exc:
        raise wire.http_error(exc) from exc
