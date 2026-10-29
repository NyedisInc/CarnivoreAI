
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import structlog

from src.core.messaging import accept, contract, message_store, notices, routing, store
from src.core.messaging.secrets import match_of

log = structlog.get_logger(__name__)

SKIPPED_KEY = "skipped_events"

DETAIL_KEY = "stream_detail"

BRIDGE_KEY = "bridge_head"

_DROP_BODY = frozenset({accept.NOT_OWNER, accept.WRONG_CONVERSATION, accept.NOT_ROUTABLE, accept.PROVIDER_DISABLED})


async def handle_event(rt: Any, state: Any, event: contract.Event) -> None:
    if event.id <= int(state.row.get("cursor") or 0):
        return
    if event.type == contract.EVENT_RECEIVED and event.message is not None:
        await _received(rt, state, event)
    elif event.type in (contract.EVENT_EDITED, contract.EVENT_UNSENT) and event.message is not None:
        await _supersede(rt, state, event)
    else:
        if event.type == contract.EVENT_HEALTH and event.health is not None:
            caps = {**state.caps, "health": {"send_ready": event.health.send_ready,
                                             "receive_ready": event.health.receive_ready,
                                             "detail": event.health.detail}}
            state.row = await asyncio.to_thread(store.update_provider, state.id, capabilities=caps) or state.row
        await asyncio.to_thread(message_store.advance_cursor, state.id, event.id)
    state.row["cursor"] = max(int(state.row.get("cursor") or 0), event.id)


async def handle_skipped(rt: Any, state: Any, skipped: contract.SkippedEvent) -> None:
    state.extra[SKIPPED_KEY] = int(state.extra.get(SKIPPED_KEY, 0)) + 1
    log.warning("messaging_event_skipped", provider_id=state.id, event_id=skipped.event_id, event_type=skipped.type,
                reason=skipped.reason, skipped_total=state.extra[SKIPPED_KEY])
    if skipped.event_id is None or skipped.event_id <= int(state.row.get("cursor") or 0):
        return
    if skipped.salvaged is not None:
        await _supersede(rt, state, contract.Event(skipped.event_id, contract.EVENT_UNSENT, None,
                                                   message=skipped.salvaged))
    else:
        await asyncio.to_thread(message_store.advance_cursor, state.id, skipped.event_id)
    state.row["cursor"] = max(int(state.row.get("cursor") or 0), skipped.event_id)


def note_bridge_head(state: Any, latest: int) -> None:
    state.extra[BRIDGE_KEY] = {"latest": int(latest), "seen_at": time.time()}


async def handle_item(rt: Any, state: Any, item: "contract.Event | contract.SkippedEvent") -> None:
    if isinstance(item, contract.SkippedEvent):
        await handle_skipped(rt, state, item)
    else:
        await handle_event(rt, state, item)


async def _conversation(state: Any, message: contract.Message) -> Any:
    return await asyncio.to_thread(store.conversation_by_match, state.id,
                                   match_of(state.secrets.match_key, message.conversation))


async def _received(rt: Any, state: Any, event: contract.Event) -> None:
    message = event.message
    conv = await _conversation(state, message)
    bindings = await asyncio.to_thread(store.list_bindings, conversation_id=conv["id"]) if conv else []
    inbound = [b for b in bindings if b["direction"] in store.INBOUND]
    recent = await asyncio.to_thread(message_store.count_since, since=time.time() - 3600, direction="in",
                                     conversation_id=conv["id"], accepted_only=True) if conv else 0
    verdict = accept.accept_received(message, enabled=bool(state.row["enabled"]), conversation_bound=conv is not None,
                                     inbound_bound=bool(inbound), owner_senders=state.owner_senders,
                                     recent_inbound=recent)
    base = {"conversation_id": conv["id"] if conv else "", "direction": "in", "kind": "message",
            "provider_message_id": message.message_id, "sent_at": message.sent_at, "in_reply_to": message.in_reply_to}
    if not verdict.accepted:
        await _refuse(rt, state, event, base, verdict.reason or "", verdict.notice, conv)
        return
    body = accept.clean_body(message.text)
    if message.has_attachments:
        body = (body + " " if body else "") + notices.copy()["messaging.batch.attachment"]
    cards = await _names(rt)
    targets = [routing.Target(b["id"], b["session_uuid"], cards.get(b["session_uuid"], b["session_uuid"][:8]),
                              b["default"]) for b in inbound]
    reply = await asyncio.to_thread(message_store.reply_binding, state.id, message.in_reply_to)
    chosen = routing.route(body, targets, reply_binding=reply)
    if chosen.reason:
        await _refuse(rt, state, event, {**base, "text": body}, chosen.reason, notices.WHICH_SESSION, conv,
                      handles=routing.handles(targets))
        return
    if not chosen.text:
        await _refuse(rt, state, event, base, accept.EMPTY, None, conv)
        return
    by_id = {b["id"]: b for b in inbound}
    rows: List[Dict[str, Any]] = [{**base, "binding_id": bid, "session_uuid": by_id[bid]["session_uuid"],
                                   "text": chosen.text, "status": "queued"} for bid in chosen.binding_ids]
    await asyncio.to_thread(message_store.record_event, state.id, event.id, rows, event_ts=event.ts)
    log.info("messaging_inbound_accepted", provider_id=state.id, event_id=event.id, via=chosen.via,
             bindings=len(rows))
    for row in rows:
        rt.wake(row["session_uuid"])


async def _refuse(rt: Any, state: Any, event: contract.Event, base: Dict[str, Any], reason: str, notice: Any,
                  conv: Any, **params: object) -> None:
    text = "" if reason in _DROP_BODY else base.get("text", accept.clean_body(event.message.text))
    row = {**base, "text": text, "status": "failed", "reason": reason}
    await asyncio.to_thread(message_store.record_event, state.id, event.id, [row], event_ts=event.ts)
    log.info("messaging_inbound_refused", provider_id=state.id, event_id=event.id, reason=reason)
    if notice and conv:
        episode = f"hour:{int(time.time() // 3600)}" if notice == accept.NOTICE_RATE else event.message.message_id
        await rt.send_notice(state, conv["id"], notice, episode, **params)


async def _supersede(rt: Any, state: Any, event: contract.Event) -> None:
    message = event.message
    conv = await _conversation(state, message)
    verdict = accept.accept_supersede(message, enabled=bool(state.row["enabled"]), conversation_bound=conv is not None,
                                      owner_senders=state.owner_senders)
    if not verdict.accepted:
        await asyncio.to_thread(message_store.advance_cursor, state.id, event.id)
        log.info("messaging_supersede_refused", provider_id=state.id, event_id=event.id, reason=verdict.reason)
        return
    new_text = accept.clean_body(message.text)
    unsent = event.type == contract.EVENT_UNSENT or not new_text
    touched = await asyncio.to_thread(
        message_store.supersede, state.id, event.id, message.message_id, unsent=unsent, new_text=new_text,
        note_for=(notices.unsent_note if unsent else (lambda _old: notices.edited_note(new_text))))
    log.info("messaging_superseded", provider_id=state.id, event_id=event.id, unsent=unsent, sessions=len(touched))
    for uuid in touched:
        rt.wake(uuid)


async def _names(rt: Any) -> Dict[str, str]:
    from src.core.messaging.delivery import session_cards

    return {uuid: str(card.get("name") or uuid[:8]) for uuid, card in (await session_cards(rt.app)).items()}
