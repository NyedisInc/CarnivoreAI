
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict, Mapping, Optional
from urllib.parse import quote

import structlog

from src.core.argent import classifier, work_items, writeback
from src.core.argent.client import ArgentError, NotFound, RateLimited, Unauthorized, Unreachable

logger = structlog.get_logger()

MAX_REASON = 200


class Refused(Exception):

    def __init__(self, status: int, code: str, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.retry_after = retry_after


def clean_reason(raw: Any, *, minimum: int) -> str:
    text = " ".join(str(raw or "").split())
    if len(text) < minimum or len(text) > MAX_REASON:
        raise Refused(422, "bad_reason", f"the reason is {minimum} to {MAX_REASON} characters" if minimum else f"the reason is at most {MAX_REASON} characters")
    if classifier.has_secret(text):
        logger.info("argent_reason_blocked_secret")
        raise Refused(422, "blocked_secret", "that text looks like it holds a credential")
    return text


_PLAIN_REFUSALS = {"argent_retag_dest_over_cap": "that item is paused or would go over its budget",
                   "retag.source_paused": "the spend sits under a paused budget, so it cannot be moved off it",
                   "retag.period_closed": "that range reaches a month that is already closed for chargeback"}
_PLAIN_BY_PATH_STATUS = {("/v1/my/retag", 400): "that time range has no spend for this session"}


def tracker_state(reply: Mapping[str, Any]) -> str:
    raw = reply.get("status_refused")
    return " ".join(raw.split())[:60] if isinstance(raw, str) else ""


async def post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not writeback.is_running():
        raise Refused(409, "feature_off", "turn the argent feature on first")
    try:
        client, _tenant = await work_items.client_for_call()
        return dict((await client.post(path, json=payload)).body)
    except Unauthorized as exc:
        raise Refused(403, "login_expired" if exc.code != "login_required" else "login_required", "log in to argent again") from None
    except NotFound:
        raise Refused(503, "unavailable", "argent cannot do that yet") from None
    except Unreachable:
        raise Refused(502, "argent_unreachable", "argent did not answer") from None
    except RateLimited as exc:
        raise Refused(429, "rate_limited", "argent is busy, try again in a minute", exc.retry_after) from None
    except ArgentError as exc:
        err = exc.body.get("error") if isinstance(exc.body.get("error"), dict) else {}
        plain = _PLAIN_REFUSALS.get(exc.code) or (_PLAIN_BY_PATH_STATUS.get((path, exc.status)))
        if plain:
            raise Refused(exc.status, exc.code or "argent_refused", plain) from None
        logger.warning("argent_refusal_unmapped", path=path, status=exc.status, code=exc.code, argent_message=str(err.get("message") or "")[:300])
        raise Refused(exc.status or 502, exc.code or "argent_refused", "argent refused") from None


async def close_item(item_id: str, reason: str = "") -> Dict[str, Any]:
    text = clean_reason(reason, minimum=0)
    tenant = await asyncio.to_thread(work_items.current_tenant)
    if not writeback.is_running():
        raise Refused(409, "feature_off", "turn the argent feature on first")
    if not tenant:
        raise Refused(403, "login_required", "log in to argent first")
    item = await asyncio.to_thread(work_items.resolve, tenant, str(item_id or "").strip())
    if item is None:
        raise Refused(404, "unknown_work_item", "that work item is not one argent has told this computer about")
    target = str(item["id"])
    reply = await post(f"/v1/my/work-items/{quote(target, safe='')}/close", {"reason": text, "comment": False})
    await _queue_done(tenant, target, text)
    work_items.poke()
    state = tracker_state(reply)
    out: Dict[str, Any] = {"work_item_id": target, "closed": True, "status_refused": reply.get("status_refused") is True or bool(state)}
    if state:
        out["tracker_state"], out["message"] = state, f"the tracker already holds a newer state ({state}), so the item was not moved"
    return out


async def _queue_done(tenant: str, item_id: str, reason: str) -> None:
    try:
        await asyncio.to_thread(writeback.enqueue_milestone, tenant, "", "", "closed", item_id, writeback.CLOSE, [], reason=reason)
        writeback.poke()
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.warning("argent_close_comment_failed", error_type=type(exc).__name__)


def item_of_origin(origin: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(origin, Mapping) or origin.get("kind") != "argent":
        return ""
    _tracker, _, item = str(origin.get("ref") or "").partition(":")
    return item


RETRY_CAP_SECONDS = 60.0
_retries: set = set()


async def _close_again(item: str, reason: str, wait: float) -> None:
    await asyncio.sleep(wait)
    try:
        await close_item(item, reason)
    except Refused as exc:
        logger.info("argent_card_close_not_posted", code=exc.code, retried=True)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("argent_card_close_failed", error_type=type(exc).__name__, retried=True)


async def on_card_closed(card: Mapping[str, Any], reason: str) -> None:
    item = item_of_origin(card.get("origin"))
    if not item or not writeback.is_running():
        return
    text = " ".join(reason.split())[:MAX_REASON]
    try:
        await close_item(item, text)
    except Refused as exc:
        logger.info("argent_card_close_not_posted", code=exc.code)
        if exc.status == 429:
            task = asyncio.get_running_loop().create_task(_close_again(item, text, min(exc.retry_after or RETRY_CAP_SECONDS, RETRY_CAP_SECONDS)))
            _retries.add(task)
            task.add_done_callback(_retries.discard)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("argent_card_close_failed", error_type=type(exc).__name__)
