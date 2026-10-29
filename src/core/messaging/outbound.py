
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

import structlog

from src.core.message_model_secrets import scan_text
from src.core.messaging import accept, message_store, store
from src.core.messaging import client
from src.core.messaging.client import ProviderError

log = structlog.get_logger(__name__)

MAX_TEXT_CHARS = 2000

PER_BINDING_PER_HOUR = 30
PER_PROVIDER_PER_HOUR = 120


class SendRefused(Exception):

    def __init__(self, status: int, code: str, retry_after: Optional[int] = None,
                 reason: Optional[str] = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.retry_after = retry_after
        self.reason = reason


_PERMANENT = frozenset({client.REFUSED, client.UNKNOWN_CONVERSATION, client.TEXT_TOO_LONG, client.REJECTED})


def refusal_for(exc: ProviderError) -> SendRefused:
    if exc.code in _PERMANENT and exc.status is not None and 400 <= exc.status < 500:
        return SendRefused(exc.status, exc.code, reason=exc.detail)
    if exc.code == client.RATE_LIMITED:
        return SendRefused(429, exc.code, retry_after=exc.retry_after, reason=exc.detail)
    if exc.code == client.NOT_READY:
        return SendRefused(503, exc.code, reason=exc.detail)
    if exc.code == client.UNCERTAIN:
        return SendRefused(409, exc.code, reason=exc.owner_text)
    return SendRefused(502, exc.code, reason=exc.detail)


def scrub(text: str) -> tuple[str, bool]:
    findings = scan_text(text)
    if not findings:
        return text, False
    chars = list(text)
    for f in findings:
        for i in range(f.offset, min(len(chars), f.offset + f.length)):
            chars[i] = "*"
    return "".join(chars), True


def _pick(bindings: list, conversation_id: Optional[str]) -> Dict[str, Any]:
    outbound = [b for b in bindings if b["direction"] in store.OUTBOUND]
    if conversation_id:
        outbound = [b for b in outbound if b["conversation_id"] == conversation_id]
    if len(outbound) != 1:
        raise SendRefused(403, "not_bound")
    return outbound[0]


async def send_as_session(rt: Any, *, session_uuid: str, session_name: str, text: str,
                          conversation_id: Optional[str] = None) -> Dict[str, Any]:
    binding = _pick(await asyncio.to_thread(store.list_bindings, session_uuid=session_uuid), conversation_id)
    conv = await asyncio.to_thread(store.get_conversation, binding["conversation_id"])
    state = rt.providers.get(conv["provider_id"]) if conv else None
    if state is None or not state.row["enabled"] or not state.caps.get("send"):
        raise SendRefused(503, "provider_unavailable")
    body = accept.clean_body(text)
    if not body:
        raise SendRefused(422, "empty")
    if len(body) > min(MAX_TEXT_CHARS, int(state.caps.get("max_text_chars") or MAX_TEXT_CHARS)):
        raise SendRefused(422, "text_too_long")
    hour = time.time() - 3600
    if (await asyncio.to_thread(message_store.count_since, since=hour, direction="out", binding_id=binding["id"])
            >= PER_BINDING_PER_HOUR or
            await asyncio.to_thread(message_store.count_since, since=hour, direction="out", provider_id=state.id)
            >= PER_PROVIDER_PER_HOUR):
        raise SendRefused(429, "rate_limited", retry_after=600)
    body, scrubbed = scrub(body)
    senders = [b for b in await asyncio.to_thread(store.list_bindings, conversation_id=conv["id"])
               if b["direction"] in store.OUTBOUND]
    if len(senders) > 1:
        body = f"[{session_name}] {body}"
    target = state.secrets.conversations.get(conv["id"])
    if not target:
        raise SendRefused(503, "provider_unavailable")
    row_id = await asyncio.to_thread(message_store.insert_outbound, {
        "provider_id": state.id, "conversation_id": conv["id"], "binding_id": binding["id"],
        "session_uuid": session_uuid, "kind": "message", "text": body})
    try:
        result = await state.client.send(target, body, reply_to=None, client_ref=row_id)
    except ProviderError as exc:
        await asyncio.to_thread(message_store.finish_outbound, row_id, status=exc.log_status, reason=exc.owner_text)
        log.warning("messaging_send_failed", provider_id=state.id, binding_id=binding["id"], code=exc.code,
                    detail=exc.detail)
        raise refusal_for(exc) from None
    await asyncio.to_thread(message_store.finish_outbound, row_id, status="delivered",
                            provider_message_id=result.message_id, sent_at=result.sent_at)
    if result.replayed:
        await asyncio.to_thread(message_store.record_replay_proof, state.id)
    log.info("messaging_sent", provider_id=state.id, binding_id=binding["id"], scrubbed=scrubbed, chars=len(body))
    return {"message_id": row_id, "sent_at": result.sent_at, "scrubbed": scrubbed}
