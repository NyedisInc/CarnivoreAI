
from __future__ import annotations

from typing import Any, Callable, Awaitable

from src.cplugs.huddle import artifacts
from src.cplugs.huddle.routes import run_store
from src.cplugs.huddle.routes_artifacts import viewer_path
from src.cplugs.sdk.browser_pages import PageNotFound, ResolvedPage

KIND = "huddle_artifact"


def resolver(ctx: Any) -> Callable[[dict], Awaitable[ResolvedPage]]:

    async def resolve(ref: dict) -> ResolvedPage:
        item_id, file_id = int(ref["item"]), str(ref["artifact"])
        meta = await run_store(lambda: artifacts.find(ctx.storage, item_id, file_id))
        if meta is None:
            raise PageNotFound(f"no artifact {file_id} on item {item_id}")
        return ResolvedPage(path=viewer_path(item_id, file_id), title=str(meta.get("title") or ""))

    return resolve


__all__ = ["KIND", "resolver"]
