
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional, Tuple, TypeVar

import structlog

from src.cplugs.publicboard.capability import client_key, forwarded_report, token_from
from src.cplugs.publicboard.health import HEALTH, ProxyHealth
from src.cplugs.publicboard.deps import BoardMissing, LinkRow, ReadDeps, RevisionRead, Unavailable, Unscannable
from src.cplugs.publicboard.ratelimit import PER_CLIENT_PER_MIN, PER_LINK_PER_MIN, RateLimiter

logger = structlog.get_logger()
MAX_REJECTED = 256
UNSCANNABLE_RETRY_S = 60.0
T = TypeVar("T")


class Refusal(Exception):

    def __init__(self, state: str) -> None:
        super().__init__(state)
        self.state = state


class Resolver:

    def __init__(self, deps: ReadDeps, per_client: int = PER_CLIENT_PER_MIN, per_link: int = PER_LINK_PER_MIN,
                 clock: Callable[[], float] = time.monotonic, health: ProxyHealth = HEALTH) -> None:
        self.deps = deps
        self._health = health
        self._clock = clock
        self._clients, self._links = RateLimiter(per_client), RateLimiter(per_link)
        self._rejected: "OrderedDict[Tuple[str, str, str], float]" = OrderedDict()

    def _charge_client(self, scope: Any) -> None:
        key = client_key(scope)
        if key is None:
            self._health.missing(forwarded_report(scope))
            raise Refusal("misrouted")
        self._health.forwarded()
        if not self._clients.allow(key):
            raise Refusal("limited")

    def _charge_link(self, link: LinkRow) -> None:
        if not self._links.allow(link.id):
            logger.warning("publicboard_link_rate_limited", link=link.id)
            raise Refusal("limited")

    async def _call(self, fn: Callable[..., T], *args: Any) -> T:
        try:
            return await asyncio.to_thread(fn, *args)
        except Unavailable as exc:
            logger.warning("publicboard_unavailable", reason=str(exc))
            raise Refusal("unavailable") from exc

    async def _read(self, link: LinkRow, revision: str, view: Optional[str]) -> RevisionRead:
        try:
            rev = await self._call(self.deps.revision, link.board, revision, view)
        except BoardMissing as exc:
            logger.info("publicboard_link_board_gone", link=link.id)
            raise Refusal("ended") from exc
        if rev is None:
            raise Refusal("unavailable")
        return rev

    def _is_refused(self, key: Tuple[str, str, str]) -> bool:
        until = self._rejected.get(key)
        if until is None:
            return False
        if self._clock() >= until:
            del self._rejected[key]
            return False
        return True

    def _refuse(self, key: Tuple[str, str, str], until: float) -> None:
        self._rejected[key] = until
        self._rejected.move_to_end(key)
        while len(self._rejected) > MAX_REJECTED:
            self._rejected.popitem(last=False)

    async def _follow(self, link: LinkRow, current: RevisionRead, view: Optional[str]) -> Optional[RevisionRead]:
        try:
            newer = await self._read(link, current.latest, view)
        except Refusal:
            return None
        newer_print = await self._call(self.deps.fingerprint, newer.texts)
        key = (link.id, newer.revision, newer_print)
        if self._is_refused(key):
            return None
        try:
            found = dict(await self._call(self.deps.scan, newer.texts))
            retry_at = float("inf")
        except Unscannable:
            found, retry_at = {"unscannable": 1}, self._clock() + UNSCANNABLE_RETRY_S
        if found:
            logger.warning("publicboard_follow_refused", link=link.id, revision=newer.revision, detectors=sorted(found))
            self._refuse(key, retry_at)
            return None
        if not await self._call(self.deps.advance, link.id, newer.revision, newer_print):
            raise Refusal("ended")
        return newer

    async def open(self, scope: Any, view: Optional[str] = None) -> Tuple[LinkRow, RevisionRead]:
        self._charge_client(scope)
        token = token_from(scope)
        checked = await self._call(self.deps.check, token or "")
        if checked.state != "ok" or checked.link is None:
            raise Refusal("ended" if checked.state == "ended" else "invalid")
        link = checked.link
        self._charge_link(link)
        rev = await self._read(link, link.revision, view)
        if not await self._call(self.deps.matches, link, rev.texts):
            logger.warning("publicboard_link_content_changed", link=link.id, revision=link.revision)
            raise Refusal("ended")
        if link.mode == "follow" and rev.latest != rev.revision:
            rev = await self._follow(link, rev, view) or rev
        return link, rev

    async def open_frame(self, scope: Any, ticket: str) -> Tuple[LinkRow, RevisionRead, str]:
        self._charge_client(scope)
        fields = await self._call(self.deps.open_ticket, ticket)
        if fields is None or len(fields) != 3:
            raise Refusal("invalid")
        link_id, revision, view = fields
        link = await self._call(self.deps.active, link_id)
        if link is None or link.revision != revision:
            raise Refusal("ended" if link is None else "invalid")
        self._charge_link(link)
        rev = await self._read(link, revision, view)
        if not await self._call(self.deps.matches, link, rev.texts):
            logger.warning("publicboard_link_content_changed", link=link.id, revision=link.revision)
            raise Refusal("ended")
        return link, rev, view
