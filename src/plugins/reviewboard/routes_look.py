
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.plugins.reviewboard import board_look, layout, wire
from src.plugins.reviewboard.errors import BoardError
from src.plugins.reviewboard.routes import Ctx, router
from src.plugins.sdk import CplugContext


class LookBody(BaseModel):
    """The look body: a theme id with its resolved palette, or both null to clear."""

    model_config = ConfigDict(extra="forbid")
    theme: Optional[str] = Field(default=None, min_length=1, max_length=64)
    palette: Optional[Dict[str, str]] = Field(default=None, max_length=board_look.MAX_ENTRIES)

    @model_validator(mode="after")
    def _both_or_neither(self) -> "LookBody":
        if (self.theme is None) != (self.palette is None):
            raise ValueError("send a theme with its palette, or neither to clear")
        for name, value in (self.palette or {}).items():
            if not board_look.NAME.fullmatch(name) or len(value) > board_look.MAX_VALUE:
                raise ValueError("a palette holds --oc- names and short values only")
        return self


@router.get("/boards/{slug}/look")
async def get_look(slug: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The board's own theme. Input: slug. Output: {look: {...} | null}."""
    try:
        wire.board_root(ctx)
        return {"look": await asyncio.to_thread(board_look.read, ctx.storage.path, slug)}
    except BoardError as exc:
        raise wire.http_error(exc) from exc


@router.put("/boards/{slug}/look")
async def put_look(slug: str, body: LookBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Keep or clear the board's own theme. Inputs: slug; body. Output: {look}. Raises: 404 (no such board), 422 (a bad body)."""
    try:
        root = wire.board_root(ctx)
        if layout.board_dir(root, slug) is None:
            raise HTTPException(status_code=404, detail={"code": "reviewboard_not_found", "detail": f"no board {slug}"})
        return {"look": await asyncio.to_thread(board_look.write, ctx.storage.path, slug, body.theme, body.palette)}
    except BoardError as exc:
        raise wire.http_error(exc) from exc

