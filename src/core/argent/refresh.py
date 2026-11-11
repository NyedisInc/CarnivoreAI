
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Set, Tuple

import structlog

from src.core import resource_push
from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentClient, ArgentError, Unauthorized, Unreachable
from src.core.argent.pair_credential import TOKEN_RE
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore, TokenUnavailable
from src.core.resource_push import topics

logger = structlog.get_logger()

REFRESH_PATH = "/v1/my/cli/refresh"
REFRESH_FRACTION = 0.8
RETRY_DELAYS = (2.0, 6.0, 15.0, 30.0)
COOLDOWN_SECONDS = 300.0
SAVE_DELAYS = (1.0, 3.0, 9.0)

REFRESHED, NEEDS_LOGIN, UNREACHABLE, NOT_OWNER, REJECTED, SKIPPED = "refreshed", "needs_login", "unreachable", "not_owner", "rejected", "skipped"


class Refresher:

    def __init__(self, store: ArgentStore, tokens: TokenStore, *, read_settings: Callable[[], Any] = settings_module.read, transport: Any = None,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 rng: Callable[[], float] = random.random) -> None:
        self._store, self._tokens, self._read_settings, self._transport = store, tokens, read_settings, transport
        self._clock, self._sleep, self._rng = clock, sleep, rng
        self._flight: Optional["asyncio.Task[str]"] = None
        self._handle: Optional[asyncio.TimerHandle] = None
        self._next_try = 0.0
        self._tasks: Set["asyncio.Task[Any]"] = set()
        self._stopped = False
        self._unsaved: Optional[Tuple[str, str, str, str, float, float]] = None

    def _snapshot(self) -> Optional[Dict[str, Any]]:
        login = self._store.get_login()
        if login is None:
            return None
        return {"login": login, "issued": self._store.login_issued_at(), "expires": float(login["expires_at"]),  # type: ignore[arg-type]
                "owner": self._store.login_source_recorded() == "own", "expired": self._store.login_expired()}

    def due_at(self, issued: float, expires: float) -> float:
        return issued + REFRESH_FRACTION * max(0.0, expires - issued)

    async def stop(self) -> None:
        self._stopped = True
        self._disarm()
        flight = self._flight
        if flight is not None and not flight.done():
            await asyncio.gather(asyncio.shield(flight), return_exceptions=True)

    def forget_unsaved(self) -> None:
        self._unsaved = None

    def _disarm(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def _arm(self, delay: float) -> None:
        self._disarm()
        if self._stopped:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._handle = loop.call_later(max(1.0, delay), self.schedule)

    def schedule(self) -> None:
        if self._stopped:
            return
        try:
            task = asyncio.get_running_loop().create_task(self.check())
        except RuntimeError:
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def check(self) -> str:
        if self._stopped:
            return SKIPPED
        snap = await asyncio.to_thread(self._snapshot)
        if snap is None or snap["expired"]:
            self._disarm()
            return SKIPPED
        if not snap["owner"]:
            self._disarm()
            return NOT_OWNER
        now = self._clock()
        if now >= snap["expires"]:
            self._disarm()
            await self._login_over()
            return NEEDS_LOGIN
        due = self.due_at(snap["issued"], snap["expires"])
        if now < due:
            self._arm(due - now)
            return SKIPPED
        if now < self._next_try:
            self._arm(self._next_try - now)
            return SKIPPED
        return await self.refresh_now()

    async def refresh_now(self) -> str:
        if self._flight is None or self._flight.done():
            self._flight = asyncio.get_running_loop().create_task(self._refresh())
        return await asyncio.shield(self._flight)

    async def _login_over(self) -> None:
        await asyncio.to_thread(self._store.mark_login_expired)
        resource_push.notify(topics.ARGENT_STATUS)

    async def _refresh(self) -> str:
        if self._unsaved is not None:
            outcome = REFRESHED if await self._save() else UNREACHABLE
        else:
            outcome = UNREACHABLE
            for attempt in range(len(RETRY_DELAYS) + 1):
                outcome = await self._attempt()
                if outcome != UNREACHABLE or self._stopped or self._unsaved is not None:
                    break
                if attempt < len(RETRY_DELAYS):
                    await self._sleep(RETRY_DELAYS[attempt] * (0.75 + 0.5 * self._rng()))
        if self._stopped:
            return outcome
        if outcome == REFRESHED:
            self._next_try = 0.0
            self.schedule()
        elif outcome == NEEDS_LOGIN:
            self._disarm()
        else:
            self._next_try = self._clock() + COOLDOWN_SECONDS
            self._arm(COOLDOWN_SECONDS)
        return outcome

    async def _attempt(self) -> str:
        snap = await asyncio.to_thread(self._snapshot)
        if snap is None or not snap["owner"]:
            return NOT_OWNER
        if self._clock() >= snap["expires"]:
            await self._login_over()
            return NEEDS_LOGIN
        login = snap["login"]
        tenant = str(login["tenant_id"])
        token = await asyncio.to_thread(self._tokens.read, tenant)
        cfg = await asyncio.to_thread(self._read_settings)
        if not token or not cfg.server_url:
            return REJECTED
        try:
            reply = await ArgentClient(cfg.server_url, lambda: token, ca_path=cfg.ca_path, transport=self._transport).post(REFRESH_PATH)
        except Unauthorized:
            await self._login_over()
            logger.info("argent_refresh_login_over")
            return NEEDS_LOGIN
        except Unreachable:
            return UNREACHABLE
        except ArgentError as exc:
            logger.info("argent_refresh_refused", status=exc.status)
            return REJECTED
        fresh, lifetime = reply.body.get("access_token"), reply.body.get("expires_in")
        if not (isinstance(fresh, str) and TOKEN_RE.fullmatch(fresh) and isinstance(lifetime, int) and not isinstance(lifetime, bool) and lifetime > 0):
            logger.info("argent_refresh_unusable_reply")
            return REJECTED
        self._unsaved = (tenant, str(login["identity_id"]), str(login["display_name"]), fresh, self._clock() + lifetime, snap["issued"])
        return REFRESHED if await self._save() else UNREACHABLE

    async def _save(self) -> bool:
        tenant, identity, display, fresh, expires, issued = self._unsaved  # type: ignore[misc]
        snap = await asyncio.to_thread(self._snapshot)
        if snap is None or not snap["owner"] or str(snap["login"]["tenant_id"]) != tenant or snap["login"]["identity_id"] != identity or snap["issued"] != issued:
            self._unsaved = None
            logger.info("argent_refresh_unsaved_dropped")
            return False
        for attempt, delay in enumerate((0.0, *SAVE_DELAYS)):
            if delay:
                await self._sleep(delay * (0.75 + 0.5 * self._rng()))
            try:
                await asyncio.to_thread(self._tokens.write, tenant, fresh)
            except TokenUnavailable:
                logger.info("argent_refresh_store_failed", attempt=attempt)
                continue
            await asyncio.to_thread(self._store.set_login, tenant, identity, display, max(1, int(expires - self._clock())), "own")
            self._unsaved = None
            resource_push.notify(topics.ARGENT_STATUS)
            logger.info("argent_refresh_done")
            return True
        return False


_current: Optional[Refresher] = None


def start() -> Refresher:
    global _current
    if _current is None:
        from src.core.argent.runtime import get_runtime  # noqa: PLC0415

        runtime = get_runtime()
        _current = Refresher(runtime.store, runtime.tokens)
    _current.schedule()
    return _current


async def stop() -> None:
    global _current
    current, _current = _current, None
    if current is not None:
        await current.stop()


def forget_unsaved() -> None:
    if _current is not None:
        _current.forget_unsaved()


def get() -> Optional[Refresher]:
    return _current


async def check_if_running() -> None:
    if _current is not None:
        await _current.check()


def poke() -> None:
    if _current is not None:
        _current.schedule()
