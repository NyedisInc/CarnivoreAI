
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Tuple

import structlog
from pydantic import ValidationError

from src.cplugs.reviewboard import document, live_text, ports, revisions, rules, store, wire
from src.cplugs.reviewboard.errors import BadRequest, BoardError, NotLive
from src.cplugs.reviewboard.live_requests import LiveSendBody
from src.cplugs.reviewboard.schema import MAX_LIVE_SENDS, LiveDelivery, LiveSend, Sidecar
from src.cplugs.reviewboard.state import board_state
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

_locks: Dict[str, asyncio.Lock] = {}


def _lock(slug: str) -> asyncio.Lock:
    return _locks.setdefault(slug, asyncio.Lock())


def _row(current: Sidecar, body: LiveSendBody, now: str) -> Dict[str, Any]:
    assert current.live is not None
    draft = current.live.draft
    answered = {a.prompt for a in body.answers}
    row = {"n": current.live.sends_total + 1, "at": now, "seq": body.seq or draft.seq, "client_round_id": body.client_round_id,
           "context": body.context.model_dump(mode="json", by_alias=True), "answers": [a.model_dump(mode="json", by_alias=True) for a in body.answers],
           "anchor_notes": [a.model_dump(mode="json", by_alias=True) for a in body.anchor_notes], "note": body.note,
           "unanswered": [p.id for p in draft.prompts if p.id not in answered], "delivery": {"state": "pending"}}
    try:
        problems = rules.answer_problems(LiveSend.model_validate(row), "the send", draft)
    except ValidationError as exc:
        raise BadRequest("the send is not valid: " + "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])) from exc
    if problems:
        raise BadRequest("the send does not fit the draft: " + "; ".join(problems[:5]))
    return row


def _find(sidecar: Sidecar, client_round_id: str) -> LiveSend:
    found = next((s for s in sidecar.live.sends if s.client_round_id == client_round_id), None) if sidecar.live else None
    if found is None:
        raise BadRequest("that send is no longer kept")
    return found


async def _deliver(ctx: CplugContext, sidecar: Sidecar, send: LiveSend) -> Tuple[Dict[str, Any], Optional[str]]:
    assert sidecar.live is not None
    text = live_text.summary(sidecar.board.title, sidecar.board.slug, send, sidecar.live.draft)
    port = ports.get()
    session = sidecar.live.by.session
    reason = "the live session was not opened by a session"
    if session:
        told = await port.tell_session(session, text)
        if told.get("told"):
            return {"state": "told", "via": str(told.get("via") or "")[:40] or None}, None
        reason = str(told.get("reason") or "the session could not be told")
    task = sidecar.task
    if task is None:
        return {"state": "undelivered", "reason": f"{reason}; the board has no task to fall back to"[:300]}, None
    try:
        ref = {"slug": sidecar.board.slug, "round": f"live{send.n}", "revision": sidecar.revisions[-1].id if sidecar.revisions else "draft"}
        posted = await port.post_reply(task.item_id, text, ref)
    except BoardError as exc:
        return {"state": "undelivered", "reason": f"{reason}; {exc}"[:300]}, None
    if not posted.get("posted"):
        return {"state": "undelivered", "reason": f"{reason}; {posted.get('reason') or 'the task did not take the reply'}"[:300]}, None
    logger.info("reviewboard_live_send_fell_back_to_task", slug=sidecar.board.slug, send=send.n, reason=reason[:120])
    return {"state": "posted"}, posted.get("tell")


def _set_delivery(client_round_id: str, delivery: Dict[str, Any]):
    def build(current: Optional[Sidecar]):
        assert current is not None
        if current.live is None or _find(current, client_round_id).delivery.state != "pending":
            raise store.NoChange()
        doc = current.model_dump(mode="json", by_alias=True)
        doc["live"]["sends"] = [{**s, "delivery": delivery} if s["client_round_id"] == client_round_id else s for s in doc["live"]["sends"]]
        return doc, {}
    return build


async def send(ctx: CplugContext, slug: str, body: LiveSendBody) -> Dict[str, Any]:
    root, state_folder = wire.board_root(ctx), ctx.storage.path
    async with _lock(slug):
        seen: Dict[str, bool] = {"duplicate": False}

        def build(current: Optional[Sidecar]):
            assert current is not None
            if current.live is None:
                raise NotLive("the board is not running live; send a round instead")
            if any(s.client_round_id == body.client_round_id for s in current.live.sends):
                seen["duplicate"] = True
                raise store.NoChange()
            doc = current.model_dump(mode="json", by_alias=True)
            row = _row(current, body, revisions.stamp(revisions.utcnow()))
            doc["live"]["sends"] = [*doc["live"]["sends"], row][-MAX_LIVE_SENDS:]
            doc["live"]["sends_total"] = row["n"]
            return doc, {}

        text, tag = await asyncio.to_thread(store.append, root, state_folder, slug, None, build)
        sidecar = document.parse_sidecar(json.loads(text))
        kept = _find(sidecar, body.client_round_id)
        tell: Optional[str] = None
        if not seen["duplicate"]:
            ctx.notify(TOPIC)
        if kept.delivery.state == "pending":
            delivery, tell = await _deliver(ctx, sidecar, kept)
            text, tag = await asyncio.to_thread(store.append, root, state_folder, slug, None, _set_delivery(body.client_round_id, delivery))
            sidecar = document.parse_sidecar(json.loads(text))
            ctx.notify(TOPIC)
        done = _find(sidecar, body.client_round_id)
        return {"send": done.model_dump(mode="json", by_alias=True), "etag": tag, "delivery": done.delivery.model_dump(mode="json"),
                "state": board_state(sidecar), "duplicate": seen["duplicate"], "tell": tell}
