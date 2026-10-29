
from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any, Awaitable, Callable, Dict

import structlog

from src.core import relay_protocol as proto
from src.core.catalog import hosted_api
from src.core.relay_identity import device_key as dk
from src.core.relay_identity.session import DeviceSession

logger = structlog.get_logger()

MAX_ATTEMPTS = 3
INSYNC_TIMEOUT_SECONDS = 120.0
INSYNC_POLL_SECONDS = 3.0

Call = Callable[..., Awaitable[hosted_api.HostedAnswer]]


class Dns01Error(Exception):
    pass


class AcmeTxtClient:

    def __init__(self, *, session: DeviceSession, control_url: str, call: Call = hosted_api.call,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self._session, self._url, self._call = session, control_url, call
        self._clock, self._sleep = clock, sleep

    async def _signed(self, action: str, arg: str) -> Dict[str, Any]:
        key = await self._session.key()
        answer = None
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                await self._sleep(proto.backoff_delay(attempt - 1))
            ts, nonce = int(self._clock()), secrets.token_bytes(16)
            body: Dict[str, Any] = {
                "device_id": key.device_id, "ts": ts, "nonce": dk.b64url(nonce), "action": action,
                "sig": key.sign(dk.acme_txt_message(key.device_id, ts, nonce, action, arg))}
            body["change_id" if action == "status" else "value"] = arg
            bearer = await self._session.account_bearer()
            auth = {"bearer": bearer} if bearer else {}
            try:
                answer = await self._call(self._url, "POST", "/acme-txt", json_body=body, **auth)
            except hosted_api.HostedUnavailable as exc:
                logger.warning("phone_link_acme_txt_unreachable", action=action, code=exc.code)
                continue
            if answer.status < 500:
                break
        if answer is None or answer.status != 200:
            code = "" if answer is None else str(answer.body.get("code", answer.status))
            raise Dns01Error(f"acme-txt {action} failed: {code or 'unreachable'}")
        return answer.body

    async def set(self, value: str) -> str:
        body = await self._signed("set", value)
        change = body.get("change_id")
        if not isinstance(change, str):
            raise Dns01Error("acme-txt set answered without a change id")
        return change

    async def clear(self, value: str) -> None:
        await self._signed("clear", value)

    async def wait_insync(self, change_id: str) -> None:
        deadline = self._clock() + INSYNC_TIMEOUT_SECONDS
        while True:
            body = await self._signed("status", change_id)
            if body.get("status") == "INSYNC":
                return
            if self._clock() >= deadline:
                raise Dns01Error("the TXT record never reached INSYNC")
            await self._sleep(INSYNC_POLL_SECONDS)

    async def publish(self, value: str) -> str:
        change = await self.set(value)
        await self.wait_insync(change)
        return change
