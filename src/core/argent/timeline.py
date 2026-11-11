
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.argent import notices, store
from src.core.argent.client import ArgentClient, ArgentError, NotFound, Unauthorized, Unreachable, error_code

logger = structlog.get_logger()

ACK_RETENTION_SECONDS = 24 * 3600
MAX_UNACKED = 20_000
RETRY_SECONDS = 60.0
PASS_LIMIT = 500


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _next_ts(previous: str, now: float) -> str:
    stamp = datetime.fromtimestamp(now, timezone.utc)
    try:
        before = datetime.strptime(previous, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc) if previous else None
    except ValueError:
        before = None
    if before is not None and stamp <= before:
        stamp = before + timedelta(microseconds=1)
    return _iso(stamp)


def record(tenant: str, session_ref: str, sub_agent_id: str, work_item_id: str, reason: str, *, state_dir: Optional[Path] = None,
           clock: Callable[[], float] = time.time) -> Optional[Dict[str, Any]]:
    now = float(clock())
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            have = conn.execute("SELECT work_item_id, ts FROM timeline_current WHERE tenant_id = ? AND session_ref = ? AND sub_agent_id = ?",
                                (tenant, session_ref, sub_agent_id)).fetchone()
            if have is not None and have["work_item_id"] == work_item_id:
                conn.execute("ROLLBACK")
                return None
            ts = _next_ts(have["ts"] if have else "", now)
            cursor = conn.execute("INSERT INTO timeline_queue (tenant_id, session_ref, sub_agent_id, work_item_id, ts, reason) VALUES (?, ?, ?, ?, ?, ?)",
                                  (tenant, session_ref, sub_agent_id, work_item_id, ts, reason))
            conn.execute("INSERT INTO timeline_current (tenant_id, session_ref, sub_agent_id, work_item_id, ts, reason) VALUES (?, ?, ?, ?, ?, ?) "
                         "ON CONFLICT(tenant_id, session_ref, sub_agent_id) DO UPDATE SET work_item_id = excluded.work_item_id, ts = excluded.ts, "
                         "reason = excluded.reason", (tenant, session_ref, sub_agent_id, work_item_id, ts, reason))
            seq = int(cursor.lastrowid or 0)
            extra = conn.execute("SELECT COUNT(*) FROM timeline_queue WHERE tenant_id = ? AND acked_at IS NULL", (tenant,)).fetchone()[0] - MAX_UNACKED
            dropped = 0
            if extra > 0:
                dropped = conn.execute("DELETE FROM timeline_queue WHERE seq IN (SELECT seq FROM timeline_queue WHERE tenant_id = ? AND acked_at IS NULL "
                                       "ORDER BY seq LIMIT ?)", (tenant, extra)).rowcount
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
    if dropped:
        notices.queue_overflow(dropped)
    return {"seq": seq, "session_id": session_ref, "sub_agent_id": sub_agent_id, "work_item_id": work_item_id, "ts": ts, "reason": reason}


def current(tenant: str, session_ref: str, *, state_dir: Optional[Path] = None) -> List[Dict[str, str]]:
    with closing(store.open_db(state_dir)) as conn:
        rows = conn.execute("SELECT sub_agent_id, work_item_id, ts, reason FROM timeline_current WHERE tenant_id = ? AND session_ref = ? "
                            "ORDER BY sub_agent_id", (tenant, session_ref)).fetchall()
    return [dict(r) for r in rows]


def effective(declared: List[Dict[str, str]], sub_agent_id: str) -> str:
    own = {d["sub_agent_id"]: d["work_item_id"] for d in declared}
    return own.get(sub_agent_id) or own.get("", "")


def backlog(tenant: str, *, state_dir: Optional[Path] = None) -> int:
    with closing(store.open_db(state_dir)) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM timeline_queue WHERE tenant_id = ? AND acked_at IS NULL", (tenant,)).fetchone()[0])


def _pending(tenant: str, state_dir: Optional[Path]) -> List[sqlite3.Row]:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("DELETE FROM timeline_queue WHERE acked_at IS NOT NULL AND acked_at < ?", (time.time() - ACK_RETENTION_SECONDS,))
        conn.commit()
        return conn.execute("SELECT seq, session_ref, sub_agent_id, work_item_id, ts, reason FROM timeline_queue WHERE tenant_id = ? AND acked_at IS NULL "
                            "ORDER BY seq LIMIT ?", (tenant, PASS_LIMIT)).fetchall()


def _ack(seq: int, state_dir: Optional[Path]) -> None:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("UPDATE timeline_queue SET acked_at = ? WHERE seq = ?", (time.time(), seq))
        conn.commit()


async def replay(client: ArgentClient, tenant: str, *, state_dir: Optional[Path] = None) -> int:
    sent, blocked = 0, set()
    for row in await asyncio.to_thread(_pending, tenant, state_dir):
        if row["session_ref"] in blocked:
            continue
        body = {"sub_agent_id": row["sub_agent_id"], "work_item_id": row["work_item_id"], "ts": row["ts"], "reason": row["reason"]}
        try:
            await client.post(f"/v1/my/sessions/{quote(str(row['session_ref']), safe='')}/context", json=body)
        except Unauthorized:
            raise
        except Unreachable as exc:
            logger.info("argent_timeline_post_failed", status=exc.status)
            return sent
        except NotFound as exc:
            if error_code(exc.body) != "not_found":
                blocked.add(row["session_ref"])
                continue
            logger.warning("argent_timeline_row_refused", status=404, code="not_found")
        except ArgentError as exc:
            if exc.status == 429:
                return sent
            logger.warning("argent_timeline_row_refused", status=exc.status, code=exc.code)
        await asyncio.to_thread(_ack, int(row["seq"]), state_dir)
        sent += 1
    return sent


class _Sender:

    task: Optional["asyncio.Task[None]"] = None
    wake: Optional[asyncio.Event] = None
    transport: Any = None


_sender = _Sender()


async def flush_once() -> bool:
    from src.core.argent import work_items
    from src.core.argent.runtime import get_runtime

    try:
        if await asyncio.to_thread(get_runtime().store.login_expired):
            return True
        client, tenant = await work_items.client_for_call()
        await replay(client, tenant)
        return await asyncio.to_thread(backlog, tenant) > 0
    except Unauthorized:
        return True
    except (sqlite3.Error, OSError) as exc:
        logger.warning("argent_timeline_flush_failed", error_type=type(exc).__name__)
        return True


async def _run() -> None:
    assert _sender.wake is not None
    while True:
        waiting = await flush_once()
        try:
            await asyncio.wait_for(_sender.wake.wait(), RETRY_SECONDS if waiting else None)
        except asyncio.TimeoutError:
            pass
        _sender.wake.clear()


def start() -> None:
    if is_running():
        return
    _sender.wake = asyncio.Event()
    _sender.task = asyncio.get_running_loop().create_task(_run())


async def stop() -> None:
    task, _sender.task = _sender.task, None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def is_running() -> bool:
    return _sender.task is not None and not _sender.task.done()


def poke() -> None:
    if _sender.wake is not None:
        _sender.wake.set()
