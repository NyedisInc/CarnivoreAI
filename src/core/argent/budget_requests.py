
from __future__ import annotations

import asyncio
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import structlog

from src.core import resource_push
from src.core.argent import notices, store, work_items
from src.core.argent.budget import money
from src.core.argent.client import ArgentClient, ArgentError, Unauthorized, Unreachable
from src.core.resource_push import topics

logger = structlog.get_logger()

MAX_REQUEST_MICROS = 1_000_000_000_000
PENDING, APPROVED, DENIED, EXPIRED = "pending", "approved", "denied", "expired"
DECIDED = (APPROVED, DENIED, EXPIRED)
KEEP_SECONDS = 30 * 86400
MAX_REASON_CHARS = 300
MAX_LIST = 100
PATH = "/v1/my/cli/budget/requests"
_TS = "%Y-%m-%dT%H:%M:%SZ"
_last_read: Dict[str, float] = {}


def _conn(state_dir: Optional[Path]) -> Any:
    return store.open_db(state_dir)


def _row(row: Any) -> Dict[str, Any]:
    return {"id": row["argent_id"], "item_id": row["item_id"], "requested_micros": row["requested_micros"], "approved_micros": row["approved_micros"],
            "state": row["state"], "decision_reason": row["decision_reason"], "created_at": row["created_at"], "decided_at": row["decided_at"]}


def record_filed(tenant: str, argent_id: str, item_id: str, requested_micros: int, *, now: Optional[float] = None, state_dir: Optional[Path] = None) -> None:
    at = time.time() if now is None else now
    with closing(_conn(state_dir)) as conn:
        conn.execute("DELETE FROM budget_requests WHERE tenant_id = ? AND state != ? AND COALESCE(decided_at, created_at) < ?", (tenant, PENDING, at - KEEP_SECONDS))
        conn.execute("INSERT OR IGNORE INTO budget_requests (tenant_id, argent_id, item_id, requested_micros, state, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (tenant, argent_id, item_id, requested_micros, PENDING, at))
        conn.commit()
    resource_push.notify(topics.ARGENT_BUDGET_REQUESTS)


def list_records(tenant: str, *, state_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    with closing(_conn(state_dir)) as conn:
        rows = conn.execute("SELECT * FROM budget_requests WHERE tenant_id = ? ORDER BY created_at DESC, argent_id DESC LIMIT ?", (tenant, MAX_LIST)).fetchall()
    return [_row(r) for r in rows]


def pending(tenant: str, *, state_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    with closing(_conn(state_dir)) as conn:
        rows = conn.execute("SELECT * FROM budget_requests WHERE tenant_id = ? AND state = ? ORDER BY created_at, argent_id", (tenant, PENDING)).fetchall()
    return [_row(r) for r in rows]


def pending_for(tenant: str, item_id: str, *, state_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    return next((r for r in pending(tenant, state_dir=state_dir) if r["item_id"] == item_id), None)


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _apply(tenant: str, remote: Mapping[str, Mapping[str, Any]], now: float, state_dir: Optional[Path]) -> List[Dict[str, Any]]:
    moved: List[Dict[str, Any]] = []
    with closing(_conn(state_dir)) as conn:
        for local in pending(tenant, state_dir=state_dir):
            row = remote.get(local["id"])
            state = row.get("state") if row else None
            if state not in DECIDED:
                continue
            approved = _int(row.get("approved_micros")) if state == APPROVED else None
            reason = row.get("decision_reason")
            reason = reason.strip()[:MAX_REASON_CHARS] if isinstance(reason, str) else ""
            conn.execute("UPDATE budget_requests SET state = ?, approved_micros = ?, decision_reason = ?, decided_at = ? WHERE tenant_id = ? AND argent_id = ? AND state = ?",
                         (state, approved, reason, now, tenant, local["id"], PENDING))
            moved.append({**local, "state": state, "approved_micros": approved, "decision_reason": reason, "decided_at": now})
        conn.commit()
    return moved


async def _announce(tenant: str, moved: List[Dict[str, Any]]) -> None:
    for rec in moved:
        item = await asyncio.to_thread(work_items.resolve, tenant, rec["item_id"])
        name = str(item.get("title") or rec["item_id"]) if item else rec["item_id"]
        amount = rec["approved_micros"] if rec["state"] == APPROVED and rec["approved_micros"] else rec["requested_micros"]
        notices.budget_request_decided(rec["id"], name, rec["state"], money(amount), rec["decision_reason"])


async def sync(client: ArgentClient, tenant: str, *, min_gap: float = 0.0, clock: Any = time.time, state_dir: Optional[Path] = None) -> int:
    waiting = await asyncio.to_thread(pending, tenant, state_dir=state_dir)
    now = clock()
    if not waiting or now - _last_read.get(tenant, 0.0) < min_gap:
        return 0
    _last_read[tenant] = now
    since = datetime.fromtimestamp(min(r["created_at"] for r in waiting) - 60, tz=timezone.utc).strftime(_TS)
    try:
        body = (await client.get(PATH, params={"since": since}, route_refusal_on_401=True)).body
    except (Unauthorized, Unreachable, ArgentError) as exc:
        logger.info("argent_budget_requests_read_failed", status=getattr(exc, "status", None), code=getattr(exc, "code", ""))
        return 0
    rows = body.get("items") if isinstance(body, dict) else None
    remote = {r["id"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)} if isinstance(rows, list) else {}
    moved = await asyncio.to_thread(_apply, tenant, remote, now, state_dir)
    if moved:
        resource_push.notify(topics.ARGENT_BUDGET_REQUESTS)
        await _announce(tenant, moved)
    return len(moved)
