
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import held, item_owner, swarm_tell, service, send_wake, told_log
from src.cplugs.huddle.held import refusal_code, refusal_reason
from src.cplugs.huddle.roles import tag_send
from src.cplugs.huddle.rules import ALL_LIST
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

Runner = Callable[[Callable[[], Any]], Awaitable[Any]]
BeforePaste = Callable[[str], Awaitable[None]]

SENT = "sent"
NO_SESSION = "no_session"
REFUSED = "refused"
HELD = held.HELD
CHANNEL_META_KIND = "source_kind"


async def paste_send(ctx: CplugContext, run: Runner, key: str, name: Optional[str], rows: List[dict],
                     target: str, reason: str, *, aggregate: bool, lead: str = "", items: Optional[List[int]] = None,
                     record: bool = True, told_at: Optional[int] = None) -> Dict[str, Any]:
    target_key = next((r["key"] for r in rows if r["id"] == target), target)
    since = await run(lambda: service.store(ctx).last_read(target_key, key, target))
    if aggregate:
        changed = await run(lambda: service.changed_for(ctx, target_key, target, key))
    else:
        changed = [(ALL_LIST, None, since or 0)] if key == ALL_LIST else None
    replies = await run(lambda: service.owner_replies(ctx, key, since, changed, items))
    text = lead + service.send_text(key, name, since, changed, items, replies)
    if told_at is None:
        told_at = await run(service.store(ctx).current_cursor)
    told = service.told_lists(ctx, key, changed) if aggregate else [key]
    pairs = [(k, c) for k, _n, c in changed] if changed else [(key, since or 0)]
    delivery_id = await swarm_tell.record_before_paste(ctx, run, target, key, pairs, bool(lead))
    try:
        result = await ctx.sessions.deliver(target, text, {CHANNEL_META_KIND: "huddle", "list": key}, recorded=delivery_id)
    except HTTPException as exc:
        await swarm_tell.discard(ctx, run, delivery_id, exc)
        raise swarm_tell.as_waking(ctx, key, exc) from exc
    if record:
        await run(lambda: service.store(ctx).record_send(told, told_at, target_key))
    label = next((r["label"] for r in rows if r["id"] == target), None)
    told_log.note(ctx, told, told_at, target_key, label or "", items, result.delivered_via)
    logger.info("task_manager_sent", list=key, target=target, reason=reason, submitted=result.submitted,
                delivered_via=result.delivered_via)
    return {"target": target, "label": label, "reason": reason, "pasted_bytes": result.pasted_bytes,
            "submitted": result.submitted, "delivered_via": result.delivered_via, "text": text}


async def send_one_of_many(ctx: CplugContext, run: Runner, key: str, name: Optional[str], infos: List[Any],
                           chosen: Optional[str], before_paste: Optional[BeforePaste] = None) -> Dict[str, Any]:
    rows = await service.candidate_rows(ctx, key, infos)
    if not rows and await swarm_tell.wake_if_asleep(ctx, key):
        rows = await service.candidate_rows(ctx, key)
    ids = {r["id"] for r in rows}
    if chosen not in ids and key.isdigit():
        rows = await send_wake.rows_with_lead(ctx, run, key, rows)
        ids = {r["id"] for r in rows}
    if chosen not in ids:
        try:
            rows = await send_wake.rows_after_wake(ctx, key, rows)
        except send_wake.WakeFailed:
            return send_wake.failed_outcome(key)
        ids = {r["id"] for r in rows}
    if chosen in ids:
        target, reason = chosen, "chosen"
    else:
        choice = await run(lambda: service.send_choice(ctx, rows, key))
        target, reason = choice["default"], choice["reason"]
    split_rows = rows + await tag_send.extra_rows(ctx, run, key, rows) if rows and not service.agent_id_of(key) else rows
    divided = await owner_split(ctx, run, key, split_rows, target, reason)
    if divided is not None:
        return await send_split(ctx, run, key, name, split_rows, divided, before_paste)
    if target is None:
        return {"list": key, "status": NO_SESSION, "sessions": rows}
    if before_paste is not None:
        await before_paste(target)
    try:
        told = await paste_send(ctx, run, key, name, rows, target, reason, aggregate=False)
    except HTTPException as exc:
        return held_or_refused(ctx, run, key, name, rows, target, reason, exc)
    held.clear(ctx, key)
    return {"list": key, "status": SENT, **told}


def held_params(name: Optional[str], reason: str, aggregate: bool, lead: str, items: Optional[List[int]], record: bool,
                told_at: Optional[int]) -> Dict[str, Any]:
    return {"name": name, "reason": reason, "aggregate": aggregate, "lead": lead, "items": items, "record": record, "told_at": told_at}


def held_deliver(ctx: CplugContext, run: Runner, key: str, target: str, rows: List[dict], params: Dict[str, Any]) -> held.Deliver:
    name, reason, aggregate = params.get("name"), params.get("reason") or "held", bool(params.get("aggregate"))
    lead, items, record, told_at = params.get("lead") or "", params.get("items"), params.get("record", True), params.get("told_at")

    async def deliver() -> Dict[str, Any]:
        if not service.agent_id_of(key):
            return await paste_send(ctx, run, key, name, rows, target, reason, aggregate=aggregate, lead=lead,
                                    items=items, record=record, told_at=told_at)
        fresh = await service.candidate_rows(ctx, key)
        if not fresh:
            raise swarm_tell.as_waking(ctx, key, HTTPException(status_code=409, detail={"code": "session_gone"}))
        return await paste_send(ctx, run, key, name, fresh, fresh[0]["id"], reason, aggregate=aggregate, lead=lead)

    return deliver


def held_or_refused(ctx: CplugContext, run: Runner, key: str, name: Optional[str], rows: List[dict], target: str,
                    reason: str, exc: HTTPException, *, aggregate: bool = False, lead: str = "",
                    items: Optional[List[int]] = None, record: bool = True, told_at: Optional[int] = None) -> Dict[str, Any]:
    code = refusal_code(exc)
    label = next((r["label"] for r in rows if r["id"] == target), None)
    logger.info("task_manager_send_refused", list=key, target=target, code=code)
    if code in held.BUSY_CODES:
        params = held_params(name, reason, aggregate, lead, items, record, told_at)
        held.hold(ctx, key, target, label, exc, held_deliver(ctx, run, key, target, rows, params), params=params)
        status = HELD
    else:
        held.record(ctx, key, target, label, exc)
        status = REFUSED
    return {"list": key, "status": status, "target": target, "label": label, "code": code, "reason": refusal_reason(exc)}


async def owner_split(ctx: CplugContext, run: Runner, key: str, rows: List[dict], default: Optional[str],
                      reason: str) -> Optional[item_owner.Split]:
    if not rows or service.agent_id_of(key):
        return None
    untold = await run(lambda: service.store(ctx).untold_owners(key))
    divided = item_owner.split(untold, rows, default, reason)
    for item_id, owner_key in divided.gone.items():
        logger.info("task_manager_owner_not_live", list=key, item=item_id, owner=owner_key, fallback=default)
    return divided if divided.divided else None


def _part_failure(ctx: CplugContext, run: Runner, key: str, name: Optional[str], rows: List[dict], part: item_owner.Part,
                  exc: HTTPException, *, first: bool, record: bool, told_at: int) -> Dict[str, Any]:
    if first:
        out = held_or_refused(ctx, run, key, name, rows, part.target or "", part.reason, exc, items=part.items,
                              record=record, told_at=told_at)
        return {k: v for k, v in out.items() if k != "list"}
    logger.info("task_manager_send_refused", list=key, target=part.target, code=refusal_code(exc))
    label = next((r["label"] for r in rows if r["id"] == part.target), None)
    return {"status": REFUSED, "target": part.target, "label": label, "code": refusal_code(exc), "reason": refusal_reason(exc)}


async def send_split(ctx: CplugContext, run: Runner, key: str, name: Optional[str], rows: List[dict], divided: item_owner.Split,
                     before_paste: Optional[BeforePaste] = None) -> Dict[str, Any]:
    told_at = await run(service.store(ctx).current_cursor)
    sent: List[Tuple[item_owner.Part, Dict[str, Any]]] = []
    failed: List[Tuple[item_owner.Part, HTTPException]] = []
    for part in divided.parts:
        if part.target is None:
            continue
        if before_paste is not None:
            await before_paste(part.target)
        try:
            told = await paste_send(ctx, run, key, name, rows, part.target, part.reason, aggregate=False, items=part.items,
                                    record=False, told_at=told_at)
        except HTTPException as exc:
            failed.append((part, exc))
            continue
        sent.append((part, {"status": SENT, **told}))
    unplaced = [p for p in divided.parts if p.target is None]
    if not failed and not unplaced:
        record_key = next((r["key"] for r in rows if r["id"] == sent[-1][0].target), sent[-1][0].target)
        await run(lambda: service.store(ctx).record_send([key], told_at, record_key))
        held.clear(ctx, key)
    others_sent = len(failed) == 1 and not unplaced
    outcomes = {id(p): o for p, o in sent}
    for at, (part, exc) in enumerate(failed):
        outcomes[id(part)] = _part_failure(ctx, run, key, name, rows, part, exc, first=at == 0, record=others_sent, told_at=told_at)
    for part in unplaced:
        outcomes[id(part)] = {"status": NO_SESSION, "target": None, "label": None}
    parts = [{**outcomes[id(p)], "reason": outcomes[id(p)].get("reason", p.reason), "items": p.items} for p in divided.parts]
    statuses = {p["status"] for p in parts}
    status = next((s for s in (NO_SESSION, HELD, REFUSED) if s in statuses), SENT)
    primary = sent[-1][1] if sent else parts[0]
    logger.info("task_manager_sent_split", list=key, status=status, parts=[(p["target"], p["status"], p["items"]) for p in parts])
    return {**primary, "list": key, "status": status, "parts": parts, **({"sessions": rows} if status == NO_SESSION else {})}
