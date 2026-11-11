
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core import resource_push
from src.core.argent import notices, row_state, timeline
from src.core.argent import settings as settings_module
from src.core.argent import store as argent_store
from src.core.argent.client import ArgentClient, ArgentError, NotFound, RateLimited, Unauthorized, Unreachable, error_code
from src.core.argent.runtime import get_runtime
from src.core.resource_push import topics
from src.core.session_token_usage.per_request import MAX_LIMIT, read_session_requests
from src.core.session_token_usage.reader import SessionSubject
from src.models.per_request_usage import RequestUsageRow

logger = structlog.get_logger()

BATCH = 200
INTERVAL = 60.0
RETRIES = 3
BACKOFF = (1.0, 3.0)
MAX_RETRY_AFTER_S = 60.0
LOOKUP_PAGE = 500


@dataclass(frozen=True)
class SpendSession:

    key: str
    subject: SessionSubject
    tmux: str = ""


class CursorStore:

    def __init__(self, state_dir: Any = None) -> None:
        self._state_dir = state_dir

    def _open(self) -> sqlite3.Connection:
        conn = argent_store._open(self._state_dir)
        conn.execute("CREATE TABLE IF NOT EXISTS fallback_spend_cursor (tenant_id TEXT NOT NULL, session_key TEXT NOT NULL, "
                     "last_at TEXT NOT NULL, PRIMARY KEY (tenant_id, session_key))")
        return conn

    def get(self, tenant_id: str, session_key: str) -> Optional[str]:
        with closing(self._open()) as conn:
            row = conn.execute("SELECT last_at FROM fallback_spend_cursor WHERE tenant_id = ? AND session_key = ?", (tenant_id, session_key)).fetchone()
        return str(row[0]) if row else None

    def set(self, tenant_id: str, session_key: str, last_at: str) -> None:
        with closing(self._open()) as conn:
            conn.execute("INSERT INTO fallback_spend_cursor (tenant_id, session_key, last_at) VALUES (?, ?, ?) "
                         "ON CONFLICT(tenant_id, session_key) DO UPDATE SET last_at = excluded.last_at", (tenant_id, session_key, last_at))
            conn.commit()


def _since(cursor: Optional[str]) -> Optional[str]:
    try:
        return cursor if cursor and datetime.fromisoformat(cursor) else None
    except ValueError:
        return None


def _safe_cursor(batch: List[RequestUsageRow], following: Optional[RequestUsageRow]) -> str:
    last = batch[-1].timestamp or ""
    if following is None or following.timestamp != last:
        return last
    earlier = [r.timestamp for r in batch if r.timestamp and r.timestamp < last]
    return earlier[-1] if earlier else last


def turn_body(row: RequestUsageRow, work_item_id: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"request_id": row.request_id, "sub_agent_id": row.agent_id, "model": row.model, "at": row.timestamp,
                            "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
                            "cache_creation_tokens": row.cache_creation_tokens, "cache_read_tokens": row.cache_read_tokens}
    if work_item_id:
        body["work_item_id"] = work_item_id
    return body


async def metered_ids(client: ArgentClient, session_key: str, since: Optional[str]) -> Set[str]:
    found: Set[str] = set()
    cursor: Optional[str] = None
    while True:
        params: Dict[str, Any] = {"limit": LOOKUP_PAGE}
        if since:
            params["since"] = since
        if cursor:
            params["cursor"] = cursor
        body = (await client.get(f"/v1/my/agent-sessions/{session_key}/usage/request-ids", params=params)).body
        found.update(i for i in body.get("items") or [] if isinstance(i, str))
        cursor = body.get("next_cursor") if isinstance(body.get("next_cursor"), str) else None
        if not cursor:
            return found


async def _post_batch(client: ArgentClient, session_key: str, turns: List[Dict[str, Any]], sleep: Callable[[float], Awaitable[Any]]) -> bool:
    for attempt in range(RETRIES):
        try:
            reply = await client.post(f"/v1/my/agent-sessions/{session_key}/usage", json={"turns": turns})
            if isinstance(reply.body, dict) and reply.body.get("work_item_ignored"):
                logger.info("argent_fallback_work_item_ignored", turns=len(turns))
            return True
        except Unauthorized:
            raise
        except Unreachable as exc:
            logger.info("argent_fallback_post_failed", status=exc.status, attempt=attempt + 1)
            if attempt + 1 < RETRIES:
                await sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
        except RateLimited as exc:
            wait = BACKOFF[min(attempt, len(BACKOFF) - 1)] if exc.retry_after is None else exc.retry_after
            logger.info("argent_fallback_rate_limited", attempt=attempt + 1, retry_after=exc.retry_after)
            if wait > MAX_RETRY_AFTER_S:
                return False
            if attempt + 1 < RETRIES:
                await sleep(wait)
        except NotFound as exc:
            if error_code(exc.body) != "not_found":
                logger.info("argent_fallback_route_missing", status=404)
                return False
            logger.warning("argent_fallback_batch_refused", status=404, code="not_found", turns=len(turns))
            return True
        except ArgentError as exc:
            logger.warning("argent_fallback_batch_refused", status=exc.status, code=exc.code, turns=len(turns))
            return True
    return False


async def _gateway_from(tenant_id: str, ref: str, state: str) -> Optional[float]:
    if state not in (row_state.PENDING, row_state.TETHERED):
        return None
    return await asyncio.to_thread(row_state.mint_epoch, tenant_id, ref)


def _epoch(stamp: Optional[str]) -> float:
    try:
        return datetime.fromisoformat(stamp).timestamp() if stamp else 0.0
    except ValueError:
        return 0.0


MINT_CLOCK_SKEW_S = 60.0


def _gateway_facts(body: Dict[str, Any]) -> Optional[Tuple[int, float]]:
    count, first = body.get("metered_count"), body.get("first_metered_at")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return None
    if first is None:
        return (count, 0.0) if count == 0 else None
    if isinstance(first, (int, float)) and not isinstance(first, bool):
        return count, float(first)
    when = _epoch(first) if isinstance(first, str) else 0.0
    return (count, when) if when else None


_settle_logged: Set[str] = set()


async def _settle_row(client: ArgentClient, tenant_id: str, ref: str, tmux: str, rows: List[RequestUsageRow], now: float) -> bool:
    mint = await asyncio.to_thread(row_state.mint_epoch, tenant_id, ref)
    if not mint:
        return False
    post = [_epoch(r.timestamp) for r in rows if _epoch(r.timestamp) >= mint]
    if not post and now - mint > row_state.TRAFFIC_GRACE_SECONDS:
        return False
    try:
        facts = _gateway_facts((await client.get(f"/v1/my/agent-sessions/{ref}/gateway")).body)
    except Unauthorized:
        raise
    except NotFound as exc:
        own = error_code(exc.body) == "not_found"
        key = ref if own else "route"
        if key not in _settle_logged:
            _settle_logged.add(key)
            if own:
                logger.warning("argent_settle_refused", ref=ref, reason="argent does not know this session as ours")
            else:
                logger.info("argent_settle_route_missing", status=404)
        return False
    except ArgentError as exc:
        logger.info("argent_settle_lookup_failed", status=exc.status, code=exc.code)
        return False
    if facts is None:
        if "shape" not in _settle_logged:
            _settle_logged.add("shape")
            logger.warning("argent_settle_unexpected_body")
        return False
    count, first = facts
    new = await asyncio.to_thread(row_state.first_traffic, tenant_id, ref, seen=count > 0 and first >= mint - MINT_CLOCK_SKEW_S, unmetered_at=min(post) if post else 0.0, now=now)
    if new:
        if new == row_state.NOT_TETHERED and await asyncio.to_thread(row_state.claim_notice, tenant_id, ref):
            notices.untethered_launch(tmux or ref, tmux or ref, row_state.NO_TRAFFIC_REASON)
        resource_push.notify(topics.ARGENT_STATUS)
        return False
    return bool(post) and (await asyncio.to_thread(row_state.lookup, tenant_id, tmux or ref))["state"] == row_state.PENDING


async def report_session(client: ArgentClient, tenant_id: str, session: SpendSession, cursors: CursorStore, *,
                         work_item_for: Optional[Callable[[RequestUsageRow], Optional[str]]] = None,
                         sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep, projects_dir: Any = None,
                         clock: Callable[[], float] = time.time) -> int:
    since = _since(cursors.get(tenant_id, session.key))
    usage = await asyncio.to_thread(read_session_requests, session.subject, since=since, limit=MAX_LIMIT, projects_dir=projects_dir)
    rows = [r for r in usage.requests if r.request_id and r.timestamp]
    if usage.state != "ok" or not rows:
        return 0
    tether = await asyncio.to_thread(row_state.lookup, tenant_id, session.tmux) if session.tmux else {"ref": session.key, "state": ""}
    ref = tether["ref"]
    if tether["state"] == row_state.PENDING and await _settle_row(client, tenant_id, ref, session.tmux, rows, clock()):
        return 0
    try:
        metered = await metered_ids(client, ref, since)
    except Unauthorized:
        raise
    except ArgentError as exc:
        logger.info("argent_fallback_lookup_failed", status=exc.status, code=exc.code)
        return 0
    state = (await asyncio.to_thread(row_state.lookup, tenant_id, session.tmux))["state"] if session.tmux else ""
    gateway_from = await _gateway_from(tenant_id, ref, state)
    unmetered = [r for r in rows if r.request_id not in metered and (gateway_from is None or _epoch(r.timestamp) < gateway_from)]
    if work_item_for is None:
        declared = await asyncio.to_thread(timeline.current, tenant_id, ref)
        work_item_for = lambda row: timeline.effective(declared, row.agent_id) or None  # noqa: E731
    sent = 0
    for start in range(0, len(unmetered), BATCH):
        batch = unmetered[start:start + BATCH]
        if not await _post_batch(client, ref, [turn_body(r, work_item_for(r)) for r in batch], sleep):
            return sent
        sent += len(batch)
        following = unmetered[start + BATCH] if start + BATCH < len(unmetered) else None
        cursors.set(tenant_id, session.key, _safe_cursor(batch, following))
    cursors.set(tenant_id, session.key, rows[-1].timestamp or "")
    return sent


def _client(tenant_id: str) -> ArgentClient:
    runtime, cfg = get_runtime(), settings_module.read()

    def expired() -> None:
        runtime.store.mark_login_expired()
        resource_push.notify(topics.ARGENT_STATUS)

    return ArgentClient(cfg.server_url, lambda: runtime.tokens.read(tenant_id), ca_path="", on_unauthorized=expired)


_manager: Any = None


def bind_session_manager(manager: Any) -> None:
    global _manager
    _manager = manager


def session_manager() -> Any:
    return _manager


async def live_sessions() -> List[SpendSession]:
    if _manager is None:
        return []
    found: List[SpendSession] = []
    for info in await _manager.list_session_infos():
        session = info.session
        if session is None or str(session.id).startswith("remote:") or info.session_row_id is None:
            continue
        tmux = info.tmux_session
        uuid = await asyncio.to_thread(_manager.claude_uuid_for_tmux_name, tmux) if tmux else None
        found.append(SpendSession(str(info.session_row_id), SessionSubject(agent_family=info.agent_family, conversation_uuid=uuid,
                                                                            working_dir=session.working_dir), tmux or ""))
    return found


async def run_pass(sessions: Callable[[], Awaitable[List[SpendSession]]] = live_sessions, cursors: Optional[CursorStore] = None) -> int:
    runtime = get_runtime()
    if not settings_module.read().enabled:
        return 0
    login = await asyncio.to_thread(runtime.store.get_login)
    if login is None or await asyncio.to_thread(runtime.store.login_expired):
        return 0
    tenant = str(login["tenant_id"])
    client, store, total = _client(tenant), cursors or CursorStore(), 0
    _known.clear()
    for session in await sessions():
        _known[session.tmux] = session
        try:
            total += await report_session(client, tenant, session, store)
        except Unauthorized:
            return total
        except (sqlite3.Error, OSError) as exc:
            logger.warning("argent_fallback_session_failed", error_type=type(exc).__name__)
    return total


_known: Dict[str, SpendSession] = {}


async def flush_ended(tenant_id: str, tmux_name: str, client: ArgentClient, *, projects_dir: Any = None) -> int:
    session = _known.pop(tmux_name, None)
    if session is None:
        return 0
    try:
        return await report_session(client, tenant_id, session, CursorStore(), projects_dir=projects_dir)
    except (ArgentError, sqlite3.Error, OSError) as exc:
        logger.info("argent_fallback_flush_failed", error_type=type(exc).__name__)
        return 0


_task: Optional["asyncio.Task[None]"] = None


async def _loop() -> None:
    while True:
        try:
            await run_pass()
        except Exception as exc:  # noqa: BLE001
            logger.warning("argent_fallback_pass_failed", error_type=type(exc).__name__)
        await asyncio.sleep(INTERVAL)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop())


async def stop() -> None:
    global _task
    task, _task = _task, None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def is_running() -> bool:
    return _task is not None and not _task.done()
