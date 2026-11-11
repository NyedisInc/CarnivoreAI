
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Literal, Optional, Tuple, TypeVar

import structlog

from src.cplugs.reviewboard.public.capability import client_key, forwarded_report, token_from
from src.cplugs.reviewboard.public.health import HEALTH, ProxyHealth
from src.cplugs.reviewboard.public.deps import BoardMissing, LinkRow, ReadDeps, RevisionRead, Unavailable, Unscannable
from src.cplugs.reviewboard.public.ratelimit import (BACKGROUND_PER_CLIENT_PER_MIN, BACKGROUND_PER_LINK_PER_MIN, PER_CLIENT_PER_MIN, PER_LINK_PER_MIN,
                                              RateLimiter)
from src.cplugs.reviewboard.public.singleflight import SingleFlight

logger = structlog.get_logger()
MAX_REJECTED = 256
UNSCANNABLE_RETRY_S = 60.0
T = TypeVar("T")
Budget = Literal["read", "background"]


class Refusal(Exception):

    def __init__(self, state: str) -> None:
        super().__init__(state)
        self.state = state


class Resolver:

    def __init__(self, deps: ReadDeps, per_client: int = PER_CLIENT_PER_MIN, per_link: int = PER_LINK_PER_MIN,
                 clock: Callable[[], float] = time.monotonic, health: ProxyHealth = HEALTH, *,
                 background_per_client: int = BACKGROUND_PER_CLIENT_PER_MIN, background_per_link: int = BACKGROUND_PER_LINK_PER_MIN) -> None:
        self.deps = deps
        self._health = health
        self._clock = clock
        self._clients = {"read": RateLimiter(per_client), "background": RateLimiter(background_per_client)}
        self._links = {"read": RateLimiter(per_link), "background": RateLimiter(background_per_link)}
        self._follows: SingleFlight[Optional[RevisionRead]] = SingleFlight()
        self._rejected: "OrderedDict[Tuple[str, str, str], float]" = OrderedDict()
        self._past_cleared: "OrderedDict[Tuple[str, str, str], None]" = OrderedDict()

    def _charge_client(self, scope: Any, budget: Budget = "read") -> None:
        key = client_key(scope)
        if key is None:
            self._health.missing(forwarded_report(scope))
            raise Refusal("misrouted")
        self._health.forwarded()
        if not self._clients[budget].allow(key):
            raise Refusal("limited")

    def _charge_link(self, link: LinkRow, budget: Budget = "read") -> None:
        if not self._links[budget].allow(link.id):
            logger.warning("publicboard_link_rate_limited", link=link.id, budget=budget)
            raise Refusal("limited")

    async def call(self, fn: Callable[..., T], *args: Any) -> T:
        try:
            return await asyncio.to_thread(fn, *args)
        except Unavailable as exc:
            logger.warning("publicboard_unavailable", reason=str(exc))
            raise Refusal("unavailable") from exc

    async def _read(self, link: LinkRow, revision: str, view: Optional[str]) -> RevisionRead:
        try:
            rev = await self.call(self.deps.revision, link.board, revision, view)
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
        if view is not None:
            return await self._follow_once(link, current, view)
        return await self._follows.run((link.id, current.latest), lambda: self._follow_once(link, current, None))

    async def _follow_once(self, link: LinkRow, current: RevisionRead, view: Optional[str]) -> Optional[RevisionRead]:
        try:
            newer = await self._read(link, current.latest, view)
        except Refusal:
            return None
        newer_print = await self.call(self.deps.fingerprint, newer.texts)
        key = (link.id, newer.revision, newer_print)
        if self._is_refused(key):
            return None
        try:
            found = dict(await self.call(self.deps.scan, newer.texts))
            retry_at = float("inf")
        except Unscannable:
            found, retry_at = {"unscannable": 1}, self._clock() + UNSCANNABLE_RETRY_S
        if found:
            logger.warning("publicboard_follow_refused", link=link.id, revision=newer.revision, detectors=sorted(found))
            self._refuse(key, retry_at)
            return None
        if not await self.call(self.deps.advance, link.id, newer.revision, newer_print):
            raise Refusal("ended")
        return newer

    async def _cleared(self, link: LinkRow, past: RevisionRead) -> bool:
        key = (link.id, past.revision, await self.call(self.deps.fingerprint, past.texts))
        if key in self._past_cleared:
            return True
        try:
            found = dict(await self.call(self.deps.scan, past.texts))
        except Unscannable:
            return False
        if found:
            logger.warning("publicboard_past_revision_refused", link=link.id, revision=past.revision, detectors=sorted(found))
            return False
        self._past_cleared[key] = None
        while len(self._past_cleared) > MAX_REJECTED:
            self._past_cleared.popitem(last=False)
        return True

    async def _past(self, link: LinkRow, revision: str, view: Optional[str]) -> Optional[RevisionRead]:
        if not await self.call(self.deps.served, link.id, revision):
            return None
        try:
            past = await self._read(link, revision, view)
        except Refusal:
            return None
        return past if await self._cleared(link, past) else None

    async def open(self, scope: Any, view: Optional[str] = None, *, budget: Budget = "read", revision: Optional[str] = None) -> Tuple[LinkRow, RevisionRead]:
        link = await self.open_link(scope, budget=budget)
        rev = await self._read(link, link.revision, view)
        if not await self.call(self.deps.matches, link, rev.texts):
            logger.warning("publicboard_link_content_changed", link=link.id, revision=link.revision)
            raise Refusal("ended")
        if link.mode == "follow" and rev.latest != rev.revision:
            rev = await self._follow(link, rev, view) or rev
        if revision is not None and revision != rev.revision:
            rev = await self._past(link, revision, view) or rev
        return link, rev

    async def open_link(self, scope: Any, *, budget: Budget = "read") -> LinkRow:
        self._charge_client(scope, budget)
        token = token_from(scope)
        checked = await self.call(self.deps.check, token or "")
        if checked.state != "ok" or checked.link is None:
            raise Refusal("ended" if checked.state == "ended" else "invalid")
        self._charge_link(checked.link, budget)
        return checked.link

    async def recheck(self, link_id: str) -> RevisionRead:
        link = await self.call(self.deps.active, link_id)
        if link is None:
            raise Refusal("ended")
        rev = await self._read(link, link.revision, None)
        if not await self.call(self.deps.matches, link, rev.texts):
            raise Refusal("ended")
        if link.mode == "follow" and rev.latest != rev.revision:
            rev = await self._follow(link, rev, None) or rev
        return rev

    async def open_frame(self, scope: Any, ticket: str) -> Tuple[LinkRow, RevisionRead, str]:
        self._charge_client(scope)
        fields = await self.call(self.deps.open_ticket, ticket)
        if fields is None or len(fields) != 3:
            raise Refusal("invalid")
        link_id, revision, view = fields
        link = await self.call(self.deps.active, link_id)
        if link is None:
            raise Refusal("ended")
        if link.revision != revision and not await self.call(self.deps.served, link.id, revision):
            raise Refusal("invalid")
        self._charge_link(link)
        rev = await self._read(link, revision, view)
        if link.revision == revision:
            if not await self.call(self.deps.matches, link, rev.texts):
                logger.warning("publicboard_link_content_changed", link=link.id, revision=link.revision)
                raise Refusal("ended")
        elif not await self._cleared(link, rev):
            raise Refusal("invalid")
        return link, rev, view
