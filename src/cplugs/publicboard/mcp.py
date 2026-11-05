
from __future__ import annotations

import asyncio
from typing import Any, Dict

from src.cplugs.publicboard import links
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ToolSpec, tool_result

NAME = "publicboard_links_remove"
_ARGS = frozenset({"link_id", "board", "all"})


async def publicboard_links_remove(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
    unknown = sorted(set(args) - _ARGS)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    given = [key for key in _ARGS if args.get(key) not in (None, False)]
    if len(given) != 1:
        raise ToolError("give exactly one of link_id, board or all=true")
    key = given[0]
    if key == "all":
        if args["all"] is not True:
            raise ToolError("all must be true")
        count = await asyncio.to_thread(links.revoke_all, ctx.storage)
    else:
        if not isinstance(args[key], str) or not args[key]:
            raise ToolError(f"{key} must be non-empty text")
        count = await asyncio.to_thread(links.revoke_link if key == "link_id" else links.revoke_board, ctx.storage, args[key])
    return tool_result({"revoked": count})


TOOLS: Dict[str, Any] = {
    NAME: ToolSpec(
        description=("End public review links so outsiders can no longer open a board: one link by id, every link of one board, or all of them. "
                     "Revoke only: a link can be made only by the owner, on the review board page."),
        properties={"link_id": {"type": "string"}, "board": {"type": "string"}, "all": {"type": "boolean"}},
        required=[], handler=publicboard_links_remove, gate="agent"),
}
