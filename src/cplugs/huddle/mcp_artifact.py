
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from src.cplugs.huddle import artifact_post, artifacts, own_list, service, steer
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError, ports
from src.cplugs.sdk.html_files import read_html_file

Runner = Callable[[Callable[[], Any]], Awaitable[Any]]
PUBLISHER_PORT = "reviewboard.artifacts"
ARGS = frozenset({"item", "title", "description", "html", "file_path", own_list.FIELD})


def read_page(path_text: Any) -> str:
    return read_html_file(path_text, artifacts.MAX_BYTES)


async def artifact(ctx: CplugContext, caller: AgentCaller, args: dict, *, run: Runner, caller_key: Callable[[], Awaitable[Any]],
                   touched: Callable[[str], Awaitable[None]], item_id: int) -> Dict[str, Any]:
    unknown = sorted(set(args) - ARGS)
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    if ("html" in args) == ("file_path" in args):
        raise ToolError("pass exactly one of html (the page text) or file_path (an absolute path to an .html file)")
    page = args["html"] if "html" in args else await run(lambda: read_page(args["file_path"]))
    board = await _as_board(ctx, caller, args, page, run=run, touched=touched, item_id=item_id)
    if board is not None:
        return board
    key = (await caller_key()) or ""
    posted = await run(lambda: artifact_post.post(ctx, item_id, args.get("title"), args.get("description"), page, author_key=key))
    await touched(posted["item"]["list"])
    meta = posted["message"]["artifact"]
    return {"item_id": item_id, "message_id": posted["message"]["id"], "title": meta["title"], "size": meta["size"],
            **steer.for_reply(True, posted["item"].get("status"))}


async def _as_board(ctx: CplugContext, caller: AgentCaller, args: dict, page: str, *, run: Runner,
                    touched: Callable[[str], Awaitable[None]], item_id: int) -> Dict[str, Any] | None:
    port = ports.get(PUBLISHER_PORT)
    if port is None:
        return None
    title, description, data = await run(lambda: artifacts.clean(args.get("title"), args.get("description"), page))
    posted = await port.publish(caller, item_id, title=title, description=description, html=page, cross_project=bool(args.get(own_list.FIELD, False)))
    if posted is None:
        return None
    item = await run(lambda: service.store(ctx).item(item_id))
    await touched(item["list"])
    return {"item_id": item_id, "message_id": (posted.get("card") or {}).get("message_id"), "title": title, "size": len(data),
            "board": posted["slug"], "revision": posted["revision"], **steer.for_reply(True, item.get("status"))}
