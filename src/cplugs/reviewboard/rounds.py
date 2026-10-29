
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import structlog

from src.cplugs.reviewboard import document, drafts, payloads, ports, revisions, round_text, service, store, wire
from src.cplugs.reviewboard.errors import BadRequest, BoardError, ReadOnlyBoard, RoundNotFound, Unlinked
from src.cplugs.reviewboard.requests import RoundBody
from src.cplugs.reviewboard.schema import Round, Sidecar
from src.cplugs.reviewboard.state import board_state
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.computer import local_computer

logger = structlog.get_logger()

JOE = "joe"
_locks: Dict[str, asyncio.Lock] = {}


def _lock(slug: str) -> asyncio.Lock:
    return _locks.setdefault(slug, asyncio.Lock())


def _round_row(current: Sidecar, body: RoundBody, now: datetime) -> Dict[str, Any]:
    revision = next((r for r in current.revisions if r.id == body.revision), None)
    if revision is None:
        raise BadRequest(f"the board has no revision {body.revision}")
    answered = {a.prompt for a in body.answers}
    n = len(current.rounds) + 1
    return {"id": f"n{n}", "n": n, "revision": body.revision, "client_round_id": body.client_round_id, "sent_at": revisions.stamp(now), "by": JOE,
            "context": body.context.model_dump(mode="json", by_alias=True),
            "answers": [a.model_dump(mode="json", by_alias=True) for a in body.answers],
            "anchor_notes": [a.model_dump(mode="json", by_alias=True) for a in body.anchor_notes],
            "note": body.note, "unanswered": [p.id for p in revision.prompts if p.id not in answered], "delivery": {"state": "pending"}}


def _payload_send(doc: Dict[str, Any], current: Sidecar, body: RoundBody, row: Dict[str, Any], now: datetime) -> None:
    revision = next(r for r in current.revisions if r.id == body.revision)
    if body.payload is None:
        raise BadRequest(f"{body.revision} holds its own answers; a send carries its payload")
    if not revision.payload_mode:
        raise BadRequest(f"{body.revision} does not hold its own answers (payload_mode); send answers to its prompts instead")
    if body.answers or body.anchor_notes:
        raise BadRequest("a payload send carries the payload and a note, not prompt answers")
    before, before_round = payloads.previous_send(current)
    row.update({"payload": body.payload, "save": payloads.add_save(doc, body.revision, body.payload, body.note, revisions.stamp(now)),
                "diff": payloads.diff(before, body.payload, before_round), "unanswered": []})


def _check_plain_send(current: Sidecar, body: RoundBody) -> None:
    revision = next((r for r in current.revisions if r.id == body.revision), None)
    if revision is not None and revision.payload_mode:
        raise BadRequest(f"{body.revision} holds its own answers; a send carries its payload")


def _find(sidecar: Sidecar, round_id: str) -> Round:
    found = next((r for r in sidecar.rounds if r.id == round_id), None)
    if found is None:
        raise RoundNotFound(f"the board has no round {round_id}")
    return found


async def _deliver(sidecar: Sidecar, round_: Round) -> Tuple[Dict[str, Any], Optional[str]]:
    def undelivered(reason: str) -> Tuple[Dict[str, Any], Optional[str]]:
        logger.info("reviewboard_round_undelivered", slug=sidecar.board.slug, round=round_.id, reason=reason)
        return {"state": "undelivered", "reason": reason[:300]}, None

    task = sidecar.task
    if task is None:
        return undelivered("the board has no task")
    here = local_computer()
    if task.computer and here and task.computer != here:
        return undelivered(f"the task is on {task.computer}")
    try:
        port = ports.get()
        if await port.item_info(task.item_id) is None:
            return undelivered(f"item {task.item_id} no longer exists")
        revision = next(r for r in sidecar.revisions if r.id == round_.revision)
        text = round_text.summary(sidecar.board.title, sidecar.board.slug, revision, round_)
        posted = await port.post_reply(task.item_id, text, {"slug": sidecar.board.slug, "round": round_.id, "revision": round_.revision})
    except BoardError as exc:
        return undelivered(str(exc))
    if not posted.get("posted"):
        return undelivered(str(posted.get("reason") or "the task did not take the reply"))
    return {"state": "posted", "item_id": task.item_id, "message_id": posted["message_id"], "at": revisions.stamp(revisions.utcnow())}, posted.get("tell")


def _set_delivery(round_id: str, delivery: Dict[str, Any]):
    def build(current: Optional[Sidecar]):
        assert current is not None
        if _find(current, round_id).delivery.state == "posted":
            raise store.NoChange()
        doc = current.model_dump(mode="json", by_alias=True)
        doc["rounds"] = [{**r, "delivery": delivery} if r["id"] == round_id else r for r in doc["rounds"]]
        return doc, {}
    return build


async def _record(ctx: CplugContext, slug: str, round_id: str, delivery: Dict[str, Any]) -> Tuple[Sidecar, str]:
    text, tag = await asyncio.to_thread(store.append, wire.board_root(ctx), ctx.storage.path, slug, None, _set_delivery(round_id, delivery))
    return document.parse_sidecar(json.loads(text)), tag


def _answer(sidecar: Sidecar, round_id: str, tag: str, duplicate: bool, tell: Optional[str] = None) -> Dict[str, Any]:
    round_ = _find(sidecar, round_id)
    return {"round": round_.model_dump(mode="json", by_alias=True), "etag": tag, "delivery": round_.delivery.model_dump(mode="json"),
            "state": board_state(sidecar), "duplicate": duplicate, "tell": tell}


async def send_round(ctx: CplugContext, slug: str, body: RoundBody) -> Dict[str, Any]:
    root, state_folder = wire.board_root(ctx), ctx.storage.path
    async with _lock(slug):
        seen: Dict[str, bool] = {"duplicate": False}

        def build(current: Optional[Sidecar]):
            assert current is not None
            if any(r.client_round_id == body.client_round_id for r in current.rounds):
                seen["duplicate"] = True
                raise store.NoChange()
            if current.task is None:
                raise Unlinked("the board has no task; link one first")
            doc = current.model_dump(mode="json", by_alias=True)
            now = revisions.utcnow()
            row = _round_row(current, body, now)
            if body.payload is not None:
                _payload_send(doc, current, body, row, now)
            else:
                _check_plain_send(current, body)
            doc["rounds"].append(row)
            return doc, {}

        text, tag = await asyncio.to_thread(store.append, root, state_folder, slug, body.base_etag, build)
        sidecar = document.parse_sidecar(json.loads(text))
        round_ = next(r for r in sidecar.rounds if r.client_round_id == body.client_round_id)
        tell: Optional[str] = None
        if not seen["duplicate"]:
            ctx.notify(TOPIC)
        if round_.delivery.state == "pending":
            delivery, tell = await _deliver(sidecar, round_)
            sidecar, tag = await _record(ctx, slug, round_.id, delivery)
            ctx.notify(TOPIC)
        if await asyncio.to_thread(drafts.clear, state_folder, slug, body.client_round_id):
            ctx.notify(drafts.TOPIC)
        return _answer(sidecar, round_.id, tag, seen["duplicate"], tell)


async def resend(ctx: CplugContext, slug: str, round_id: str) -> Dict[str, Any]:
    root = wire.board_root(ctx)
    async with _lock(slug):
        found = await asyncio.to_thread(service.board, root, slug)
        if not isinstance(found.get("sidecar"), dict) or found["status"] != "ok":
            raise ReadOnlyBoard(f"{slug} is not a board this build can write")
        current = document.parse_sidecar(found["sidecar"])
        if _find(current, round_id).delivery.state == "posted":
            return _answer(current, round_id, found["etag"], True)
        delivery, tell = await _deliver(current, _find(current, round_id))
        sidecar, tag = await _record(ctx, slug, round_id, delivery)
        ctx.notify(TOPIC)
        return _answer(sidecar, round_id, tag, False, tell)
