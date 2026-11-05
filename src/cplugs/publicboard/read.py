
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

import structlog

from src.cplugs.publicboard.assets import asset_file, asset_headers
from src.cplugs.publicboard.deps import ReadDeps, Unavailable
from src.cplugs.publicboard.headers import frame_headers
from src.cplugs.publicboard.respond import Handler, send_body, send_json, send_state
from src.cplugs.publicboard.resolve import Refusal, Resolver

logger = structlog.get_logger()
FRAME_PATH = re.compile(r"/f/([A-Za-z0-9_-]{22}\.r[1-9][0-9]{0,5}\.[a-z][a-z0-9-]{0,23}\.[0-9]{10}\.[A-Za-z0-9_-]{43})")
TICKET_LABEL = "publicboard-frame-v1"
TICKET_TTL_S = 300


class Reader:

    def __init__(self) -> None:
        self.resolver: Optional[Resolver] = None

    def bind(self, deps: ReadDeps) -> None:
        self.resolver = Resolver(deps)

    def unbind(self) -> None:
        self.resolver = None


READER = Reader()


def board_wire(link_expires: int, projection: Dict[str, Any], mint: Callable[[str], str]) -> Dict[str, Any]:
    views = [{**view, "frame": f"/f/{mint(view['id'])}"} for view in projection["views"]]
    return {**projection, "views": views, "expires_at": link_expires}


async def board(scope: Any, receive: Any, send: Any) -> None:
    resolver = READER.resolver
    if resolver is None:
        await send_state(send, "unavailable")
        return
    try:
        link, rev = await resolver.open(scope)
        deps = resolver.deps
        body = board_wire(link.expires_at, dict(rev.projection), lambda view: deps.mint_ticket([link.id, rev.revision, view]))
    except Refusal as refused:
        await send_state(send, refused.state)
        return
    except Unavailable:
        await send_state(send, "unavailable")
        return
    await send_json(send, 200, body)


async def frame(scope: Any, receive: Any, send: Any) -> None:
    resolver = READER.resolver
    match = FRAME_PATH.fullmatch(scope["raw_path"].decode("ascii"))
    if resolver is None or match is None:
        await send_state(send, "unavailable" if resolver is None else "invalid")
        return
    try:
        _, rev, _ = await resolver.open_frame(scope, match.group(1))
    except Refusal as refused:
        await send_state(send, refused.state)
        return
    if rev.page is None:
        await send_state(send, "invalid")
        return
    await send_body(send, 200, frame_headers(), "text/html; charset=utf-8", rev.page)


def shell_route(path: str) -> Handler:
    async def handler(scope: Any, receive: Any, send: Any) -> None:
        try:
            content_type, body = asset_file(path)
        except OSError:
            logger.error("publicboard_asset_unreadable", path=path)
            await send_state(send, "unavailable")
            return
        await send_body(send, 200, asset_headers(), content_type, body)
    return handler
