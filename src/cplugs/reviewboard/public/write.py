
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.cplugs.reviewboard.public.capability import client_key, visitor_key
from src.cplugs.reviewboard.public.deps import BoardMissing, CapSpent, Unscannable, WriteDeps
from src.cplugs.reviewboard.public.ratelimit import DRAFTS_PER_CLIENT_PER_MIN, POSTS_PER_CLIENT_PER_MIN, RateLimiter
from src.cplugs.reviewboard.public.read import READER
from src.cplugs.reviewboard.public.respond import Handler, send_json, send_state
from src.cplugs.reviewboard.public.resolve import Refusal
from src.cplugs.reviewboard.public.submission import Malformed, Submission, comment as parse_comment, draft as parse_draft, parse_json

logger = structlog.get_logger()
MAX_BODY_BYTES = 64 * 1024
BODY_DEADLINE_S = 10.0


class Writer:

    def __init__(self) -> None:
        self.deps: Optional[WriteDeps] = None
        self.posts = RateLimiter(POSTS_PER_CLIENT_PER_MIN)
        self.drafts = RateLimiter(DRAFTS_PER_CLIENT_PER_MIN)

    def bind(self, deps: WriteDeps, posts_per_min: int = POSTS_PER_CLIENT_PER_MIN, drafts_per_min: int = DRAFTS_PER_CLIENT_PER_MIN) -> None:
        self.deps, self.posts, self.drafts = deps, RateLimiter(posts_per_min), RateLimiter(drafts_per_min)

    def unbind(self) -> None:
        self.deps = None


WRITER = Writer()


async def read_body(receive: Any) -> bytes:
    async def collect() -> bytes:
        chunks: List[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                raise Malformed("disconnected")
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                raise Malformed("body too big")
            chunks.append(chunk)
            if not message.get("more_body"):
                return b"".join(chunks)

    try:
        return await asyncio.wait_for(collect(), BODY_DEADLINE_S)
    except asyncio.TimeoutError as exc:
        raise Malformed("body too slow") from exc


async def _accept(scope: Any, body: bytes, parse: Callable[[dict], Submission], deps: WriteDeps) -> bool:
    resolver = READER.resolver
    if resolver is None:
        raise Refusal("unavailable")
    link, rev = await resolver.open(scope)
    if not link.writable:
        logger.info("publicboard_post_read_only", link=link.id)
        raise Refusal("read_only")
    if not WRITER.posts.allow(client_key(scope) or ""):
        raise Refusal("limited")
    try:
        post = parse(parse_json(body))
    except Malformed as exc:
        logger.info("publicboard_post_malformed", link=link.id, why=str(exc))
        raise Refusal("malformed") from exc
    key = visitor_key(scope)
    revision = await _answered(link, rev.revision, post.revision)
    await _judge(link.id, link.board, revision, post.kind, post.body, post.texts, deps)
    try:
        stored = await resolver.call(deps.store, link.id, link.board, revision, post.kind, post.name, post.body, post.client_post_id, key)
    except CapSpent as exc:
        raise Refusal("full") from exc
    return stored.duplicate


async def _answered(link: Any, serving: str, named: Optional[str]) -> str:
    if named is None or named == serving:
        return serving
    resolver = READER.resolver
    if resolver is None:
        raise Refusal("unavailable")
    if not await resolver.call(resolver.deps.served, link.id, named):
        raise Refusal("stale")
    return named


async def _board_problems(board: str, revision: str, kind: str, body: Any, deps: WriteDeps) -> Sequence[str]:
    resolver = READER.resolver
    if resolver is None:
        raise Refusal("unavailable")
    try:
        problems = await resolver.call(deps.check, board, revision, kind, body)
    except BoardMissing as exc:
        logger.info("publicboard_post_board_missing", board=board, revision=revision)
        raise Refusal("ended") from exc
    if problems is None:
        raise Refusal("unavailable")
    return problems


async def _judge(link_id: str, board: str, revision: str, kind: str, body: Any, texts: Any, deps: WriteDeps) -> None:
    resolver = READER.resolver
    if resolver is None:
        raise Refusal("unavailable")
    problems = await _board_problems(board, revision, kind, body, deps)
    if problems:
        logger.info("publicboard_post_rejected", link=link_id, kind=kind, problems=len(problems))
        raise _Rejected()
    try:
        found = dict(await resolver.call(resolver.deps.scan, list(texts)))
    except Unscannable as exc:
        raise Refusal("unavailable") from exc
    if found:
        logger.warning("publicboard_post_has_secret", link=link_id, detectors=sorted(found))
        raise _HasSecret(sorted(found))


async def _accept_draft(scope: Any, body: bytes, deps: WriteDeps) -> bool:
    resolver = READER.resolver
    if resolver is None:
        raise Refusal("unavailable")
    link = await resolver.open_link(scope, budget="background")
    if not link.writable:
        logger.info("publicboard_draft_read_only", link=link.id)
        raise Refusal("read_only")
    key = visitor_key(scope)
    if key is None:
        raise Refusal("malformed")
    if not WRITER.drafts.allow(f"{client_key(scope) or ''}|{key}"):
        raise Refusal("limited")
    try:
        draft = parse_draft(parse_json(body))
    except Malformed as exc:
        logger.info("publicboard_draft_malformed", link=link.id, why=str(exc))
        raise Refusal("malformed") from exc
    revision = await _answered(link, link.revision, draft.revision)
    if draft.body.get("answers") != []:
        await _judge(link.id, link.board, revision, "answers", draft.body, draft.texts, deps)
    else:
        await _board_problems(link.board, revision, "answers", draft.body, deps)
    try:
        return bool(await resolver.call(deps.save_draft, link.id, link.board, key, revision, draft.body))
    except CapSpent as exc:
        raise Refusal("full") from exc


class _Rejected(Exception):
    pass


class _HasSecret(Exception):

    def __init__(self, detectors: List[str]) -> None:
        super().__init__("has_secret")
        self.detectors = detectors


def _post_route(parse: Callable[[dict], Submission]) -> Handler:
    async def accept(scope: Any, body: bytes, deps: WriteDeps) -> Tuple[int, Dict[str, Any]]:
        duplicate = await _accept(scope, body, parse, deps)
        return (200 if duplicate else 201), {"state": "received", "duplicate": duplicate}
    return _route(accept)


async def _draft_accept(scope: Any, body: bytes, deps: WriteDeps) -> Tuple[int, Dict[str, Any]]:
    return 200, {"state": "saved", "changed": await _accept_draft(scope, body, deps)}


def _route(accept: Callable[[Any, bytes, WriteDeps], Awaitable[Tuple[int, Dict[str, Any]]]]) -> Handler:
    async def handler(scope: Any, receive: Any, send: Any) -> None:
        deps = WRITER.deps
        try:
            body = await read_body(receive)
        except Malformed:
            await send_state(send, "malformed")
            return
        if deps is None:
            await send_state(send, "unavailable")
            return
        try:
            status, answer = await accept(scope, body, deps)
        except Refusal as refused:
            await send_state(send, refused.state)
            return
        except _Rejected:
            await send_state(send, "rejected")
            return
        except _HasSecret as secret:
            await send_state(send, "has_secret", {"detectors": secret.detectors})
            return
        await send_json(send, status, answer)
    return handler


comments = _post_route(parse_comment)
draft = _route(_draft_accept)
