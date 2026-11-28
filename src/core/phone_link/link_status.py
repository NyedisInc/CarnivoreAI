
from __future__ import annotations

import hashlib
import secrets
import time
from typing import Callable

import structlog

from src.core.relay_identity import device_key as dk
from src.core.relay_identity.session import UNREACHABLE, DeviceSession, RelayAuthError


class LinkStatusError(ValueError):
    pass


logger = structlog.get_logger()

STATUSES = ("up", "signed_out")
_last_seq = 0


def next_seq(clock: Callable[[], float] = time.time) -> int:
    global _last_seq
    _last_seq = max(int(clock() * 1000), _last_seq + 1)
    return _last_seq


async def report(session: DeviceSession, status: str, clock: Callable[[], float] = time.time) -> bool:
    if status not in STATUSES:
        raise LinkStatusError("status must be up or signed_out")
    key = await session.key()
    ts, seq = int(clock()), next_seq(clock)
    body = {"device_id": key.device_id, "ts": ts, "seq": seq, "status": status,
            "sig": key.sign(dk.link_status_message(key.device_id, ts, seq, status))}
    answer = await session.post_signed("/link-status", body)
    if answer.status != 200:
        logger.info("link_status_report_refused", status=answer.status, code=str(answer.body.get("code", "")))
    return answer.status == 200


async def issue_key(session: DeviceSession, clock: Callable[[], float] = time.time) -> str:
    token = secrets.token_urlsafe(24)
    key = await session.key()
    ts, nonce = int(clock()), secrets.token_bytes(16)
    key_hash = hashlib.sha256(token.encode("ascii")).digest()
    body = {"device_id": key.device_id, "ts": ts, "nonce": dk.b64url(nonce), "key_hash": dk.b64url(key_hash),
            "sig": key.sign(dk.status_key_message(key.device_id, ts, nonce, key_hash))}
    answer = await session.post_signed("/status-key", body)
    if answer.status != 200:
        raise RelayAuthError(UNREACHABLE, f"status key refused: {answer.status}")
    return token
