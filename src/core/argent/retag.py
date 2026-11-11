
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from src.core.argent import store, work_items, writeback
from src.core.argent.close import Refused, clean_reason, post

MAX_RANGE_DAYS = 31
FUTURE_SLACK_SECONDS = 300
MIN_REASON = 3


def _moment(raw: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        raise Refused(422, "bad_range", f"{label} is not a date and time") from None
    if parsed.tzinfo is None:
        raise Refused(422, "bad_range", f"{label} needs a time zone")
    return parsed.astimezone(timezone.utc)


def check_range(since: Any, until: Any, *, now: Optional[float] = None) -> Tuple[str, str]:
    start, end = _moment(since, "since"), _moment(until, "until")
    if end <= start:
        raise Refused(422, "bad_range", "the range must end after it starts")
    if end.timestamp() > (time.time() if now is None else now) + FUTURE_SLACK_SECONDS:
        raise Refused(422, "bad_range", "the range cannot end in the future")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise Refused(422, "range_too_long", f"the range is at most {MAX_RANGE_DAYS} days")
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), end.strftime(fmt)


def own_ref(tenant: str, tmux_name: str) -> str:
    with closing(store.open_db()) as conn:
        row = conn.execute("SELECT session_ref FROM ref_alias WHERE tenant_id = ? AND tmux_name = ?", (tenant, tmux_name)).fetchone()
    return str(row[0]) if row else ""


async def retag(tmux_name: str, since: Any, until: Any, to_item_id: str, reason: Any) -> Dict[str, Any]:
    text = clean_reason(reason, minimum=MIN_REASON)
    first, last = check_range(since, until)
    if not writeback.is_running():
        raise Refused(409, "feature_off", "turn the argent feature on first")
    tenant = await asyncio.to_thread(work_items.current_tenant)
    if not tenant:
        raise Refused(403, "login_required", "log in to argent first")
    try:
        ref = await asyncio.to_thread(own_ref, tenant, tmux_name)
    except (sqlite3.Error, OSError):
        ref = ""
    if not ref:
        raise Refused(404, "not_own_session", "only a session this computer runs, with an argent id, can be re-tagged")
    item = await asyncio.to_thread(work_items.resolve, tenant, str(to_item_id or "").strip())
    if item is None:
        raise Refused(404, "unknown_work_item", "that work item is not one argent has told this computer about")
    return await post("/v1/my/retag", {"session_id": ref, "since": first, "until": last, "to_work_item_id": str(item["id"]), "reason": text})
