
from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from src.core import relay_protocol as proto
from src.core.catalog import hosted_api
from src.core.relay_identity import device_key as dk
from src.core.relay_identity.session import DeviceSession

logger = structlog.get_logger()

MAX_ATTEMPTS = 3
STATES = frozenset({"none", "pending", "live", "dead", "lockout", "released"})
Call = Callable[..., Awaitable[hosted_api.HostedAnswer]]


class CustomDomainError(Exception):

    def __init__(self, status: int, code: str, detail: str = "") -> None:
        super().__init__(f"{status} {code}")
        self.status, self.code, self.detail = status, code, detail


def clean_view(body: Dict[str, Any]) -> Dict[str, Any]:
    def text(key: str) -> Optional[str]:
        value = body.get(key)
        return value if isinstance(value, str) else None

    def whole(value: Any) -> Optional[int]:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    check = body.get("check")
    if isinstance(check, dict):
        seen = check.get("seen")
        check = {"result": str(check.get("result", "")), "seen": seen if isinstance(seen, str) else None,
                 "checked_at": whole(check.get("checked_at"))}
    else:
        check = None
    state = text("state")
    return {"domain": text("domain"), "state": state if state in STATES else "none", "target": text("target"),
            "dead_reason": text("dead_reason"), "lockout_until": whole(body.get("lockout_until")),
            "check": check, "repair": whole(body.get("repair")) or 0}


class ControlClient:

    def __init__(self, *, session: DeviceSession, control_url: str, call: Call = hosted_api.call,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self._session, self._url, self._call = session, control_url, call
        self._clock, self._sleep = clock, sleep

    async def act(self, action: str, domain: str = "", acct_uri: str = "") -> Dict[str, Any]:
        key = await self._session.key()
        bearer = await self._session.account_bearer()
        if not bearer:
            raise CustomDomainError(403, "account_required", "sign in with a carnivore account")
        answer: Optional[hosted_api.HostedAnswer] = None
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                await self._sleep(proto.backoff_delay(attempt - 1))
            ts, nonce = int(self._clock()), secrets.token_bytes(16)
            body = {"device_id": key.device_id, "ts": ts, "nonce": dk.b64url(nonce), "action": action,
                    "sig": key.sign(dk.custom_domain_message(key.device_id, ts, nonce, action, domain, acct_uri))}
            if domain:
                body["domain"] = domain
            if acct_uri:
                body["acct_uri"] = acct_uri
            try:
                answer = await self._call(self._url, "POST", "/custom-domain", json_body=body, bearer=bearer)
            except hosted_api.HostedUnavailable as exc:
                logger.warning("custom_domain_control_unreachable", action=action, code=exc.code)
                continue
            if answer.status < 500:
                break
        if answer is None:
            raise CustomDomainError(0, "unreachable", "the control plane could not be reached")
        if answer.status != 200:
            raise CustomDomainError(answer.status, str(answer.body.get("code", answer.status)),
                                    str(answer.body.get("detail", "")))
        return clean_view(answer.body)
