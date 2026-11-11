
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog

from src.cplugs.reviewboard.public.assets import asset_file, asset_headers
from src.cplugs.reviewboard.public.capability import reviewed_revision, visitor_key
from src.cplugs.reviewboard.public.deps import ReadDeps, Unavailable
from src.cplugs.reviewboard.public.headers import frame_headers
from src.cplugs.reviewboard.public.respond import Handler, send_body, send_json, send_state
from src.cplugs.reviewboard.public.resolve import Refusal, Resolver
from src.cplugs.reviewboard.public.theme import ThemeRefused, clean_theme

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


def board_wire(link_expires: int, projection: Dict[str, Any], mint: Callable[[str], str], frame_ttl: int,
               look: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    views = [{**view, "frame": f"/f/{mint(view['id'])}"} for view in projection["views"]]
    return {**projection, "views": views, "expires_at": link_expires, "frame_ttl": frame_ttl, **(look or {})}


async def _own_draft(resolver: Resolver, link: Any, key: Optional[str], revision: str) -> Optional[Mapping[str, object]]:
    if key is None or link.access != "answer":
        return None
    try:
        return await resolver.call(resolver.deps.own_draft, link.id, key, revision)
    except Refusal as refused:
        logger.warning("publicboard_own_draft_unread", link=link.id, state=refused.state)
        return None


async def _strip(resolver: Resolver, link: Any, key: Optional[str]) -> List[Dict[str, Any]]:
    try:
        served = list(await resolver.call(resolver.deps.served_revisions, link.id)) or [link.revision]
        mine = set(await resolver.call(resolver.deps.answered_revisions, link.id, key)) if key and link.access == "answer" else set()
    except Refusal as refused:
        logger.warning("publicboard_strip_unread", link=link.id, state=refused.state)
        return [{"revision": link.revision, "answered": False}]
    return [{"revision": rev, "answered": rev in mine} for rev in served]


def _board_palette(palette: Any) -> Optional[Dict[str, str]]:
    if not palette:
        return None
    try:
        return clean_theme(palette)
    except ThemeRefused:
        logger.warning("publicboard_board_palette_unusable", entries=len(palette) if hasattr(palette, "__len__") else None)
        return None


async def board(scope: Any, receive: Any, send: Any) -> None:
    resolver = READER.resolver
    if resolver is None:
        await send_state(send, "unavailable")
        return
    try:
        link, rev = await resolver.open(scope, revision=reviewed_revision(scope))
        deps = resolver.deps
        key = visitor_key(scope)
        own = await _own_draft(resolver, link, key, rev.revision)
        strip = await _strip(resolver, link, key)
        palette = await resolver.call(deps.board_theme, link.board)
        theme = _board_palette(palette)
        look = {"access": link.access, "theme": theme or (dict(link.theme) if link.theme else None), "draft": own,
                "revisions": strip}
        body = board_wire(link.expires_at, dict(rev.projection), lambda view: deps.mint_ticket([link.id, rev.revision, view]),
                         deps.ticket_ttl_s, look)
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
