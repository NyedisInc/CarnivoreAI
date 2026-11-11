
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import urlsplit

import structlog

from src.core import resource_push
from src.core.argent import health, refresh, settings as settings_module
from src.core.argent.client import ArgentClient, ArgentError, Unreachable, error_code
from src.core.argent.delegate import Delegates
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore, TokenUnavailable
from src.core.resource_push import topics

logger = structlog.get_logger()

IDLE, PENDING, DONE, EXPIRED, DENIED, FAILED = "idle", "pending", "done", "expired", "denied", "failed"
DEFAULT_INTERVAL, DEFAULT_EXPIRES, SLOW_DOWN_STEP = 5, 600, 5
MAX_UNREACHABLE = 5


def poke_after_login() -> None:
    from src.core.argent import cards_sync, cost_poller, refresh, timeline, work_items  # noqa: PLC0415

    health.poke()
    work_items.poke()
    timeline.poke()
    cards_sync.poke()
    cost_poller.poke()
    refresh.poke()


class LoginRefused(ValueError):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DeviceLogin:

    def __init__(self, store: ArgentStore, tokens: TokenStore, *, transport: Any = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self._store, self._tokens, self._transport, self._clock, self._sleep = store, tokens, transport, clock, sleep
        self._task: Optional["asyncio.Task[None]"] = None
        self._state: Dict[str, Any] = {"state": IDLE}

    def public(self) -> Dict[str, Any]:
        return dict(self._state)

    def _set(self, **fields: Any) -> None:
        self._state = {**self._state, **fields}
        resource_push.notify(topics.ARGENT_STATUS)

    async def start(self, server_url: str) -> Dict[str, Any]:
        if not server_url:
            raise LoginRefused("server_url_empty", "set the argent server address first")
        await self.cancel()
        try:
            reply = await ArgentClient(server_url, transport=self._transport).post("/v1/my/cli/device", auth=False)
        except Unreachable as exc:
            raise LoginRefused("server_unreachable", "argent did not answer") from exc
        except ArgentError as exc:
            raise LoginRefused("login_refused", "argent refused to start a login") from exc
        body = reply.body
        device_code, user_code = body.get("device_code"), body.get("user_code")
        link = body.get("verification_uri_complete") or body.get("verification_uri")
        if not (isinstance(device_code, str) and device_code and isinstance(user_code, str) and isinstance(link, str)) or urlsplit(link).scheme not in ("http", "https"):
            raise LoginRefused("login_unusable", "argent answered with an unusable login")
        interval = max(1, int(body.get("interval") or DEFAULT_INTERVAL))
        expires_in = max(1, int(body.get("expires_in") or DEFAULT_EXPIRES))
        self._state = {"state": PENDING, "user_code": user_code, "verification_uri": link, "expires_at": self._clock() + expires_in, "interval": interval}
        resource_push.notify(topics.ARGENT_STATUS)
        self._task = asyncio.get_running_loop().create_task(self._poll(server_url, device_code, interval, self._state["expires_at"]))
        return self.public()

    async def cancel(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._state.get("state") == PENDING:
            self._state = {"state": IDLE}

    async def _poll(self, server_url: str, device_code: str, interval: float, deadline: float) -> None:
        client = ArgentClient(server_url, transport=self._transport)
        silent = 0
        while self._clock() < deadline:
            await self._sleep(interval)
            try:
                body = (await client.post("/v1/my/cli/token", json={"device_code": device_code}, auth=False)).body
                code = error_code(body)
            except Unreachable:
                silent += 1
                if silent >= MAX_UNREACHABLE:
                    return self._set(state=FAILED, reason="server_unreachable")
                continue
            except ArgentError as exc:
                body, code = {}, exc.code
            silent = 0
            if not code and body.get("access_token"):
                return await self._finish(body)
            if code == "authorization_pending":
                continue
            if code == "slow_down":
                interval += SLOW_DOWN_STEP
                continue
            return self._set(state={"expired_token": EXPIRED, "access_denied": DENIED}.get(code, FAILED), reason=code or "login_failed")
        self._set(state=EXPIRED, reason="expired_token")

    async def _finish(self, body: Dict[str, Any]) -> None:
        token, tenant = body.get("access_token"), body.get("tenant_id")
        if not (isinstance(token, str) and isinstance(tenant, str) and tenant):
            return self._set(state=FAILED, reason="login_unusable")
        refresh.forget_unsaved()
        await Delegates(self._store, self._tokens).revoke_all()
        try:
            await asyncio.to_thread(self._tokens.write, tenant, token)
        except TokenUnavailable:
            return self._set(state=FAILED, reason="keychain_unavailable")
        previous = await asyncio.to_thread(self._store.set_login, tenant, str(body.get("identity_id") or ""), str(body.get("display_name") or ""), int(body.get("expires_in") or 0))
        await asyncio.to_thread(settings_module.update, lambda block: block.update(tokenPointer=self._tokens.pointer(tenant)))
        poke_after_login()
        from src.core.argent import pair_sync  # noqa: PLC0415

        pair_sync.login_changed()
        self._set(state=DONE, tenant_changed_from=previous or "", reason="")
        logger.info("argent_login_done", tenant_changed=bool(previous))
