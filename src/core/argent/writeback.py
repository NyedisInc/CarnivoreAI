
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import structlog

from src.config import settings as app_settings
from src.core import resource_push
from src.core.db import DatastoreUnreadableError, db_path_for, get_meta
from src.core.db_models import META_INSTALL_ID
from src.core.db_reuse.core_read import lend_pooled_or_raise
from src.core.argent import classifier, notices, store, summarizer, timeline, work_items, writeback_template
from src.core.argent.budget import money
from src.core.argent.client import ArgentClient, ArgentError, NotFound, RateLimited, Unauthorized
from src.core.argent.runtime import get_runtime
from src.core.resource_push import topics

logger = structlog.get_logger()

WINDOW_SECONDS = 600.0
MAX_ROWS = 2000
MAX_ATTEMPTS = 8
BACKOFF_SECONDS = 60.0
MAX_BACKOFF = 3600.0
KEEP_FINISHED_SECONDS = 24 * 3600
LOGIN_RETRY_SECONDS = 300.0

COLLECTING, REVIEW, READY, POSTED, DISCARDED, BLOCKED, FAILED = "collecting", "review", "ready", "posted", "discarded", "blocked", "failed"
FINISHED = (POSTED, DISCARDED, BLOCKED, FAILED)
COMMIT, PICKED, CLOSE = "commit", "picked", "close"
MILESTONES = (COMMIT, PICKED, CLOSE)


class EditError(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def beast_armed() -> bool:
    from src.core.mcp import beast_mode  # noqa: PLC0415

    return beast_mode.stored_armed()


def _conn(state_dir: Optional[Path]) -> sqlite3.Connection:
    return store.open_db(state_dir)


def _view(row: sqlite3.Row) -> Dict[str, Any]:
    payload = json.loads(row["payload"] or "{}")
    return {"id": row["id"], "item_id": row["item_id"], "milestone": row["milestone"], "state": row["state"], "body": row["body"], "session_name": row["session_name"],
            "commits": len(payload.get("commits", [])), "created_at": row["created_at"], "result": row["result"]}


def _prune(conn: sqlite3.Connection, tenant: str, now: float) -> None:
    conn.execute("DELETE FROM writeback WHERE tenant_id = ? AND state IN (?, ?, ?, ?) AND created_at < ?", (tenant, *FINISHED, now - KEEP_FINISHED_SECONDS))
    extra = conn.execute("SELECT COUNT(*) FROM writeback WHERE tenant_id = ?", (tenant,)).fetchone()[0] - MAX_ROWS
    if extra > 0:
        conn.execute("DELETE FROM writeback WHERE id IN (SELECT id FROM writeback WHERE tenant_id = ? AND state != ? ORDER BY (state IN (?, ?, ?, ?)) DESC, id LIMIT ?)",
                     (tenant, REVIEW, *FINISHED, extra))


def enqueue_milestone(tenant: str, ref: str, tmux_name: str, session_name: str, item_id: str, milestone: str, commits: List[Dict[str, Any]], *,
                      reason: str = "", now: Optional[float] = None, state_dir: Optional[Path] = None) -> int:
    if milestone not in MILESTONES or not item_id:
        raise ValueError("a write-back needs a milestone and an item")
    moment = time.time() if now is None else now
    with closing(_conn(state_dir)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if milestone == COMMIT:
                last = conn.execute("SELECT MAX(composed_at) FROM writeback WHERE tenant_id = ? AND item_id = ? AND milestone = ?", (tenant, item_id, COMMIT)).fetchone()[0] or 0.0
                due = max(moment, last + WINDOW_SECONDS)
                waiting = conn.execute("SELECT id, payload FROM writeback WHERE tenant_id = ? AND session_ref = ? AND item_id = ? AND milestone = ? AND state = ?",
                                       (tenant, ref, item_id, COMMIT, COLLECTING)).fetchone()
                if waiting is not None:
                    merged = json.loads(waiting["payload"])
                    known = {c["sha"] for c in merged.get("commits", [])}
                    merged["commits"] = merged.get("commits", []) + [c for c in commits if c["sha"] not in known]
                    conn.execute("UPDATE writeback SET payload = ?, session_name = ? WHERE id = ?", (json.dumps(merged), session_name, waiting["id"]))
                    conn.execute("COMMIT")
                    return int(waiting["id"])
            else:
                due = moment
            cur = conn.execute("INSERT INTO writeback (tenant_id, session_ref, tmux_name, session_name, item_id, milestone, state, payload, created_at, due_at) "
                               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (tenant, ref, tmux_name, session_name, item_id, milestone, COLLECTING,
                                                                          json.dumps({"commits": commits, "reason": reason}), moment, due))
            _prune(conn, tenant, moment)
            conn.execute("COMMIT")
            return int(cur.lastrowid or 0)
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise


def on_commits(tenant: str, ref: str, tmux_name: str, session_name: str, made: List[Any], *, state_dir: Optional[Path] = None) -> int:
    declared = timeline.current(tenant, ref, state_dir=state_dir)
    by_item: Dict[str, List[Dict[str, Any]]] = {}
    for commit in made:
        item = timeline.effective(declared, commit.sub_agent_id)
        if item:
            by_item.setdefault(item, []).append({"sha": commit.sha, "subject": commit.subject, "files": list(commit.files), "file_count": commit.file_count})
    for item, rows in by_item.items():
        enqueue_milestone(tenant, ref, tmux_name, session_name, item, COMMIT, rows, state_dir=state_dir)
    if by_item:
        poke()
    return len(by_item)


def end_session(tmux_name: str, *, now: Optional[float] = None, state_dir: Optional[Path] = None) -> int:
    with closing(_conn(state_dir)) as conn:
        done = conn.execute("UPDATE writeback SET due_at = ? WHERE tmux_name = ? AND state = ?", (time.time() if now is None else now, tmux_name, COLLECTING)).rowcount
        conn.commit()
    if done:
        poke()
    return done



def _title(tenant: str, item_id: str) -> str:
    row = work_items.resolve(tenant, item_id)
    return str(row.get("title") or item_id) if row else item_id


def review_list(tenant: str, *, state_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    with closing(_conn(state_dir)) as conn:
        rows = conn.execute("SELECT * FROM writeback WHERE tenant_id = ? AND state = ? ORDER BY id", (tenant, REVIEW)).fetchall()
    return [{**_view(r), "item_title": _title(tenant, r["item_id"])} for r in rows]


def _review_row(conn: sqlite3.Connection, tenant: str, row_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM writeback WHERE id = ? AND tenant_id = ?", (row_id, tenant)).fetchone()
    if row is None:
        raise EditError("not_found")
    if row["state"] != REVIEW:
        raise EditError("not_in_review")
    return row


def edit(tenant: str, row_id: int, body: str, *, state_dir: Optional[Path] = None) -> Dict[str, Any]:
    text = writeback_template.clean(body, writeback_template.MAX_BODY)
    if not text:
        raise EditError("empty")
    if classifier.has_secret(text):
        logger.info("argent_writeback_edit_blocked_secret")
        raise EditError("blocked_secret")
    with closing(_conn(state_dir)) as conn:
        _review_row(conn, tenant, row_id)
        conn.execute("UPDATE writeback SET body = ? WHERE id = ?", (text, row_id))
        conn.commit()
        row = conn.execute("SELECT * FROM writeback WHERE id = ?", (row_id,)).fetchone()
    resource_push.notify(topics.ARGENT_WRITEBACK)
    return _view(row)


def approve(tenant: str, row_id: int, *, state_dir: Optional[Path] = None) -> Dict[str, Any]:
    with closing(_conn(state_dir)) as conn:
        _review_row(conn, tenant, row_id)
        conn.execute("UPDATE writeback SET state = ?, next_try = 0 WHERE id = ?", (READY, row_id))
        conn.commit()
        row = conn.execute("SELECT * FROM writeback WHERE id = ?", (row_id,)).fetchone()
    notices.writeback_review_resolved(row_id)
    resource_push.notify(topics.ARGENT_WRITEBACK)
    poke()
    return _view(row)


def discard(tenant: str, row_id: int, *, state_dir: Optional[Path] = None) -> Dict[str, Any]:
    with closing(_conn(state_dir)) as conn:
        _review_row(conn, tenant, row_id)
        conn.execute("UPDATE writeback SET state = ? WHERE id = ?", (DISCARDED, row_id))
        conn.commit()
        row = conn.execute("SELECT * FROM writeback WHERE id = ?", (row_id,)).fetchone()
    notices.writeback_review_resolved(row_id)
    resource_push.notify(topics.ARGENT_WRITEBACK)
    return _view(row)



def _set(row_id: int, state_dir: Optional[Path], **fields: Any) -> None:
    with closing(_conn(state_dir)) as conn:
        conn.execute(f"UPDATE writeback SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), row_id))
        conn.commit()


def _rows(tenant: str, sql: str, args: tuple, state_dir: Optional[Path]) -> List[sqlite3.Row]:
    with closing(_conn(state_dir)) as conn:
        return conn.execute(sql, (tenant, *args)).fetchall()


def _who(tenant: str) -> str:
    login = get_runtime().store.get_login()
    return str(login.get("display_name") or "") if login and str(login.get("tenant_id")) == tenant else ""


async def _window_cost(client: ArgentClient, item_id: str, since: float) -> str:
    params: Dict[str, Any] = {"by": "work_item", "id": item_id}
    if since > 0:
        params["since"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))
    try:
        reply = await client.get("/v1/my/cost", params=params)
    except ArgentError as exc:
        logger.info("argent_writeback_cost_unavailable", status=exc.status)
        return "-"
    rows = reply.body.get("items")
    row = next((r for r in rows if isinstance(r, dict) and r.get("id") == item_id), None) if isinstance(rows, list) else None
    micros = row.get("cost_micros") if isinstance(row, dict) else None
    return money(micros) if isinstance(micros, int) and not isinstance(micros, bool) and micros >= 0 else "-"


async def compose(client: ArgentClient, tenant: str, row: sqlite3.Row, state_dir: Optional[Path], now: float, *, chat: Any = None) -> None:
    payload = json.loads(row["payload"] or "{}")
    commits = payload.get("commits", [])
    title = await asyncio.to_thread(_title, tenant, row["item_id"])
    who = await asyncio.to_thread(_who, tenant)
    previous = await asyncio.to_thread(_last_composed, tenant, row["item_id"], row["id"], state_dir)
    cost = await _window_cost(client, row["item_id"], previous)
    subjects = [str(c.get("subject", "")) for c in commits]
    paths = [p for c in commits for p in c.get("files", [])]
    file_count = sum(int(c.get("file_count", 0)) for c in commits)
    said = summarizer.Summary(reason="nothing_to_say")
    if row["milestone"] == CLOSE:
        said = summarizer.Summary(text=("closed: " + str(payload.get("reason", ""))).strip(), reason="close")
    elif commits:
        said = await summarizer.summarize(subjects, paths, chat=chat)
    body = writeback_template.build(title, who, row["session_name"] or row["tmux_name"], subjects, len(commits), paths, file_count, cost, said.text)
    found = classifier.has_secret(*subjects, *paths, said.text, body)
    if found:
        logger.info("argent_writeback_blocked_secret", findings=found)
        await asyncio.to_thread(_set, row["id"], state_dir, state=BLOCKED, composed_at=now)
        notices.writeback_blocked_secret(row["id"], title)
        return
    if said.result is not None:
        ref = row["session_ref"]
        rows = (await asyncio.to_thread(work_items.list_rows, tenant))["items"]
        await classifier.report_spend(client, ref, classifier.project_of(rows, row["item_id"]), said.result)
    armed = await asyncio.to_thread(beast_armed)
    await asyncio.to_thread(_set, row["id"], state_dir, state=READY if armed else REVIEW, body=body, composed_at=now)
    if not armed:
        notices.writeback_review(row["id"], title)
        resource_push.notify(topics.ARGENT_WRITEBACK)


def _last_composed(tenant: str, item_id: str, row_id: int, state_dir: Optional[Path]) -> float:
    with closing(_conn(state_dir)) as conn:
        value = conn.execute("SELECT MAX(composed_at) FROM writeback WHERE tenant_id = ? AND item_id = ? AND id != ?", (tenant, item_id, row_id)).fetchone()[0]
    return float(value or 0.0)


def install_id() -> str:
    with closing(lend_pooled_or_raise(db_path_for(app_settings.get_state_dir()))) as conn:
        return str(get_meta(conn, META_INSTALL_ID) or "")


def idempotency_key(tenant: str, row: sqlite3.Row) -> str:
    seed = "|".join((install_id(), tenant, str(row["id"]), repr(row["created_at"])))
    return "cwb-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]


async def send(client: ArgentClient, tenant: str, row: sqlite3.Row, state_dir: Optional[Path], now: float) -> None:
    title = await asyncio.to_thread(_title, tenant, row["item_id"])
    if classifier.has_secret(row["body"]):
        await asyncio.to_thread(_set, row["id"], state_dir, state=BLOCKED)
        notices.writeback_blocked_secret(row["id"], title)
        return
    attempts = int(row["attempts"]) + 1
    try:
        key = await asyncio.to_thread(idempotency_key, tenant, row)
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("argent_writeback_no_install_id", error_type=type(exc).__name__)
        await _retry(row, attempts, state_dir, 0, now)
        return
    try:
        reply = await client.post(f"/v1/my/work-items/{quote(str(row['item_id']), safe='')}/writeback", json={"kind": "comment", "body": row["body"]},
                                  headers={"Idempotency-Key": key})
    except Unauthorized:
        await asyncio.to_thread(_set, row["id"], state_dir, next_try=now + LOGIN_RETRY_SECONDS)
        return
    except NotFound as exc:
        await _retry(row, attempts, state_dir, exc.status, now)
        return
    except RateLimited as exc:
        await _retry(row, attempts, state_dir, exc.status, now, minimum=exc.retry_after or 0.0)
        return
    except ArgentError as exc:
        if exc.status == 409 and exc.code == "tracker.not_connected":
            await _retry(row, attempts, state_dir, exc.status, now)
            return
        if exc.status and exc.status < 500:
            logger.info("argent_writeback_refused_by_argent", status=exc.status, code=exc.code)
            await asyncio.to_thread(_set, row["id"], state_dir, state=FAILED, attempts=attempts, result=exc.code or str(exc.status))
            return
        await _retry(row, attempts, state_dir, exc.status, now)
        return
    refused = reply.body.get("status_refused") is True
    await asyncio.to_thread(_set, row["id"], state_dir, state=POSTED, attempts=attempts, result="status_refused" if refused else "ok")
    if refused:
        notices.writeback_refused(row["id"], title)


async def _retry(row: sqlite3.Row, attempts: int, state_dir: Optional[Path], status: int, now: float, minimum: float = 0.0) -> None:
    if attempts >= MAX_ATTEMPTS:
        logger.warning("argent_writeback_gave_up", status=status)
        await asyncio.to_thread(_set, row["id"], state_dir, state=FAILED, attempts=attempts, result="gave_up")
        return
    delay = max(minimum, min(MAX_BACKOFF, BACKOFF_SECONDS * (2 ** (attempts - 1))))
    await asyncio.to_thread(_set, row["id"], state_dir, attempts=attempts, next_try=now + delay)


async def run_pass(client: ArgentClient, tenant: str, *, state_dir: Optional[Path] = None, now: Optional[float] = None, chat: Any = None) -> Optional[float]:
    moment = time.time() if now is None else now
    for row in await asyncio.to_thread(_rows, tenant, "SELECT * FROM writeback WHERE tenant_id = ? AND state = ? AND due_at <= ? ORDER BY id", (COLLECTING, moment), state_dir):
        await compose(client, tenant, row, state_dir, moment, chat=chat)
    for row in await asyncio.to_thread(_rows, tenant, "SELECT * FROM writeback WHERE tenant_id = ? AND state = ? AND next_try <= ? ORDER BY id", (READY, moment), state_dir):
        await send(client, tenant, row, state_dir, moment)
    return await asyncio.to_thread(_next_wake, tenant, moment, state_dir)


def _next_wake(tenant: str, now: float, state_dir: Optional[Path]) -> Optional[float]:
    with closing(_conn(state_dir)) as conn:
        due = conn.execute("SELECT MIN(due_at) FROM writeback WHERE tenant_id = ? AND state = ?", (tenant, COLLECTING)).fetchone()[0]
        retry = conn.execute("SELECT MIN(next_try) FROM writeback WHERE tenant_id = ? AND state = ?", (tenant, READY)).fetchone()[0]
    times = [t for t in (due, retry) if t is not None]
    return max(1.0, min(times) - now) if times else None



class _Runner:

    task: Optional["asyncio.Task[None]"] = None
    wake: Optional[asyncio.Event] = None
    loop: Optional["asyncio.AbstractEventLoop"] = None


_runner = _Runner()


async def pass_once() -> Optional[float]:
    try:
        client, tenant = await work_items.client_for_call()
        return await run_pass(client, tenant)
    except Unauthorized:
        return LOGIN_RETRY_SECONDS if await asyncio.to_thread(_has_waiting) else None
    except (sqlite3.Error, OSError) as exc:
        logger.warning("argent_writeback_pass_failed", error_type=type(exc).__name__)
        return BACKOFF_SECONDS


def _has_waiting() -> bool:
    with closing(_conn(None)) as conn:
        return conn.execute("SELECT 1 FROM writeback WHERE state IN (?, ?) LIMIT 1", (COLLECTING, READY)).fetchone() is not None


async def _run() -> None:
    assert _runner.wake is not None
    while True:
        wait = await pass_once()
        try:
            await asyncio.wait_for(_runner.wake.wait(), wait)
        except asyncio.TimeoutError:
            pass
        _runner.wake.clear()


def start() -> None:
    if is_running():
        return
    _runner.wake = asyncio.Event()
    _runner.loop = asyncio.get_running_loop()
    _runner.task = _runner.loop.create_task(_run())


async def stop() -> None:
    task, _runner.task = _runner.task, None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def is_running() -> bool:
    return _runner.task is not None and not _runner.task.done()


def poke() -> None:
    loop, wake = _runner.loop, _runner.wake
    if loop is not None and wake is not None and not loop.is_closed():
        loop.call_soon_threadsafe(wake.set)


async def on_session_event(event: Any) -> None:
    from src.core.sessions.session_events import ENDED  # noqa: PLC0415

    if getattr(event, "kind", "") != ENDED:
        return
    try:
        await asyncio.to_thread(end_session, event.tmux_name)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("argent_writeback_end_failed", error_type=type(exc).__name__)
