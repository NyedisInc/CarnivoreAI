
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from src.core.catalog import hosted_api
from src.core.native_push import payload_crypto
from src.core.native_push.store import NativeDeviceStore
from src.core.notifications.destinations import secrets as secret_store
from src.core.relay_identity import device_key as dk
from src.core.relay_identity.session import DeviceSession, RelayAuthError
from src.core.web_push import vapid

logger = structlog.get_logger()

COALESCE_SECONDS = 10.0
_COALESCE_KEYS_MAX = 2048
# could not
STATUS_NO_ANSWER = 0
STATUS_NOT_SIGNED_IN = 403
STATUS_INVALID = 422

Call = Callable[..., Awaitable[hosted_api.HostedAnswer]]
SessionProvider = Callable[[], Awaitable[Optional[DeviceSession]]]


def push_base_url(control_url: str) -> str:
    base = control_url.rstrip("/")
    return base[: -len("/relay")] if base.endswith("/relay") else base


class ApnsSender:

    def __init__(self, *, store: NativeDeviceStore, secrets: Any, session: SessionProvider, control_url: str,
                 on_gone: Optional[Callable[[str], Awaitable[None]]] = None, call: Call = hosted_api.call,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._store, self._secrets, self._session = store, secrets, session
        self._base, self._on_gone, self._call, self._clock = push_base_url(control_url), on_gone, call, clock
        self._typed_last: Dict[tuple, float] = {}

    def _coalesced(self, row_id: str, type_id: str, instance: str) -> bool:
        last = self._typed_last.get((row_id, type_id, instance))
        return last is not None and 0 <= self._clock() - last < COALESCE_SECONDS

    def _record_delivered(self, row_id: str, type_id: str, instance: str) -> None:
        if len(self._typed_last) >= _COALESCE_KEYS_MAX:
            self._typed_last.pop(next(iter(self._typed_last)))
        self._typed_last[(row_id, type_id, instance)] = self._clock()

    async def _payload_key(self, row_id: str) -> Optional[bytes]:
        found = await self._secrets.get(row_id)
        raw = (found or {}).get("payload_key")
        if not isinstance(raw, str):
            return None
        try:
            decoded = vapid.b64url_decode(raw)
        except ValueError:
            return None
        return decoded if len(decoded) == payload_crypto.KEY_BYTES else None

    async def send_typed(self, row_id: str, type_id: str, payload: Dict[str, str], instance: str = "") -> Optional[int]:
        """Push one typed ``{title, body, path}`` to ONE native device.

        Output: None when the device is unknown; 200 on delivery or when coalesced; 410 when the relay says the
        device is unregistered (the row and key are deleted); 0 when the relay could not be reached; 403 when no
        account bearer is available; 422 when the key is missing or the payload cannot be sealed; else the relay's status.
        Example: ``await sender.send_typed("d_0123456789ab", "session.finished", {...}, "session-1")``.
        """
        row = next((r for r in await asyncio.to_thread(self._store.list) if r["id"] == row_id), None)
        if row is None:
            return None
        if self._coalesced(row_id, type_id, instance):
            return 200
        try:
            key = await self._payload_key(row_id)
        except secret_store.SecretError as exc:
            logger.warning("apns_key_unreadable", device=row_id, error_type=type(exc).__name__)
            return STATUS_NO_ANSWER
        if key is None:
            logger.warning("apns_key_missing", device=row_id)
            return STATUS_INVALID
        try:
            blob = payload_crypto.seal(key, row_id, json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        except ValueError as exc:
            logger.warning("apns_seal_failed", device=row_id, error_type=type(exc).__name__)
            return STATUS_INVALID
        status = await self._post(row, blob, hashlib.sha256(f"{type_id}\0{instance}".encode("utf-8")).hexdigest()[:24])
        if status == 200:
            self._record_delivered(row_id, type_id, instance)
        elif status == 410:
            await self._forget(row_id)
        if status is not None:
            await asyncio.to_thread(self._store.record_result, row_id, status)
        return status

    async def _post(self, row: Dict[str, Any], blob: bytes, collapse_id: str) -> int:
        session = await self._session()
        if session is None:
            return STATUS_NO_ANSWER
        try:
            key = await session.key()
            bearer = await session.account_bearer()
        except RelayAuthError as exc:
            logger.warning("apns_relay_identity_unavailable", error_type=type(exc).__name__)
            return STATUS_NO_ANSWER
        if not bearer:
            return STATUS_NOT_SIGNED_IN
        ts, nonce = int(time.time()), secrets.token_bytes(16)
        body = {"device_id": key.device_id, "ts": ts, "nonce": dk.b64url(nonce), "environment": row["environment"],
                "token": row["token"], "collapse_id": collapse_id,
                "payload": base64.b64encode(blob).decode("ascii"),
                "sig": key.sign(dk.apns_message(key.device_id, ts, nonce, row["environment"], row["token"], collapse_id, blob))}
        try:
            answer = await self._call(self._base, "POST", "/push/apns", json_body=body, bearer=bearer)
        except hosted_api.HostedUnavailable as exc:
            logger.info("apns_relay_unreachable", device=row["id"], code=exc.code)
            return STATUS_NO_ANSWER
        logger.info("apns_relay_answered", device=row["id"], status=answer.status, code=str(answer.body.get("code", ""))[:40])
        return answer.status

    async def _forget(self, row_id: str) -> None:
        await asyncio.to_thread(self._store.remove, row_id)
        try:
            await self._secrets.delete(row_id)
        except secret_store.SecretError as exc:
            logger.warning("native_push_key_delete_failed", device=row_id, error_type=type(exc).__name__)
        if self._on_gone is not None:
            await self._on_gone(row_id)
        logger.info("apns_device_gone", device=row_id)
