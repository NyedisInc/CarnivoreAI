
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import closing
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core import resource_push
from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentClient, ArgentError, NotFound, Unauthorized, Unreachable
from src.core.argent.runtime import get_runtime
from src.core.argent.store import open_db
from src.core.resource_push import topics

logger = structlog.get_logger()

PAGE_LIMIT = 500
MAX_PAGES = 40
SLOW_SECONDS, FAST_SECONDS, VIEW_WINDOW = 300.0, 60.0, 120.0
MAX_MERGE_HOPS = 10
KINDS = ("project", "feature", "story")
SPRINT_STATES = ("active", "future", "closed", "none")

OK, PENDING, LOGIN_REQUIRED, LOGIN_EXPIRED, UNAVAILABLE = "ok", "pending", "login_required", "login_expired", "unavailable"


class _Pull:

    task: Optional["asyncio.Task[None]"] = None
    wake: Optional[asyncio.Event] = None
    state: str = PENDING
    viewed_at: float = 0.0
    client: Optional[ArgentClient] = None
    client_key: str = ""
    token: Optional[str] = None
    transport: Any = None


_pull = _Pull()


def touch() -> None:
    _pull.viewed_at = time.monotonic()


def _clean_row(row: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
        return None
    out = dict(row)
    out["kind"] = row.get("kind") if row.get("kind") in KINDS else "unknown"
    if "sprint_state" in out and out["sprint_state"] not in SPRINT_STATES:
        out["sprint_state"] = "unknown"
    return out


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _write_rows(conn: sqlite3.Connection, tenant: str, rows: Dict[str, Dict[str, Any]]) -> None:
    for row in rows.values():
        conn.execute(
            "INSERT OR REPLACE INTO work_items (tenant_id, id, kind, parent_id, title, status, merged_into, updated_at, raw) VALUES (?,?,?,?,?,?,?,?,?)",
            (tenant, row["id"], row["kind"], row.get("parent_id") if isinstance(row.get("parent_id"), str) else None, _text(row.get("title")),
             _text(row.get("status")), row.get("merged_into") if isinstance(row.get("merged_into"), str) and row["merged_into"] else None,
             _text(row.get("updated_at")), json.dumps(row, sort_keys=True)))


def replace_all(tenant: str, rows: List[Dict[str, Any]], rev: Optional[int]) -> bool:
    fresh = {r["id"]: r for r in map(_clean_row, rows) if r}
    with closing(open_db()) as conn:
        before = {r[0]: r[1] for r in conn.execute("SELECT id, raw FROM work_items WHERE tenant_id = ?", (tenant,))}
        after = {k: json.dumps(v, sort_keys=True) for k, v in fresh.items()}
        conn.execute("BEGIN IMMEDIATE")
        if before != after:
            conn.execute("DELETE FROM work_items WHERE tenant_id = ?", (tenant,))
            _write_rows(conn, tenant, fresh)
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (f"work_items_rev:{tenant}", json.dumps(rev)))
        conn.execute("COMMIT")
    return before != after


def upsert(tenant: str, row: Dict[str, Any]) -> bool:
    clean = _clean_row(row)
    if clean is None:
        return False
    with closing(open_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _write_rows(conn, tenant, {clean["id"]: clean})
        conn.execute("COMMIT")
    return True


def list_rows(tenant: str, *, kind: str = "", parent_id: str = "", sprint_state: str = "", q: str = "") -> Dict[str, Any]:
    with closing(open_db()) as conn:
        found = conn.execute("SELECT raw FROM work_items WHERE tenant_id = ? AND merged_into IS NULL AND (? = '' OR kind = ?) "
                             "AND (? = '' OR parent_id = ?) AND (? = '' OR instr(lower(title), lower(?)) > 0) "
                             "ORDER BY updated_at DESC, id", (tenant, kind, kind, parent_id, parent_id, q, q)).fetchall()
        rev = conn.execute("SELECT value FROM meta WHERE key = ?", (f"work_items_rev:{tenant}",)).fetchone()
    items = [json.loads(r[0]) for r in found]
    return {"items": [i for i in items if not sprint_state or i.get("sprint_state") == sprint_state], "rev": json.loads(rev[0]) if rev else None}


def resolve(tenant: str, item_id: str) -> Optional[Dict[str, Any]]:
    seen: set = set()
    with closing(open_db()) as conn:
        current: Optional[str] = item_id
        for _ in range(MAX_MERGE_HOPS + 1):
            if not current or current in seen:
                return None
            seen.add(current)
            row = conn.execute("SELECT raw, merged_into FROM work_items WHERE tenant_id = ? AND id = ?", (tenant, current)).fetchone()
            if row is None:
                return None
            if not row[1]:
                return json.loads(row[0])
            current = row[1]
    return None


def _tenant_and_token() -> Tuple[str, Optional[str]]:
    runtime = get_runtime()
    login = runtime.store.get_login()
    if not login:
        return "", None
    return str(login["tenant_id"]), runtime.tokens.read(str(login["tenant_id"]))


def current_tenant() -> str:
    login = get_runtime().store.get_login()
    return str(login["tenant_id"]) if login else ""


def _client(server_url: str) -> ArgentClient:
    key = server_url
    if _pull.client is None or _pull.client_key != key:
        _pull.client = ArgentClient(server_url, lambda: _pull.token, transport=_pull.transport, on_unauthorized=get_runtime().store.mark_login_expired)
        _pull.client_key = key
    return _pull.client


async def client_for_call() -> Tuple[ArgentClient, str]:
    cfg = await asyncio.to_thread(settings_module.read)
    tenant, token = await asyncio.to_thread(_tenant_and_token)
    if not (cfg.server_url and tenant and token):
        raise Unauthorized("log in to argent first", 401, "login_required")
    _pull.token = token
    return _client(cfg.server_url), tenant


async def pull_once() -> str:
    try:
        client, tenant = await client_for_call()
    except Unauthorized:
        _pull.state = LOGIN_REQUIRED
        return _pull.state
    try:
        rows: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        rev: Optional[int] = None
        for page in range(MAX_PAGES):
            params: Dict[str, Any] = {"limit": PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            reply = await client.get("/v1/my/work-items", params=params)
            if reply.not_modified and page == 0:
                _pull.state = OK
                return _pull.state
            rows += [r for r in reply.body.get("items", []) if isinstance(r, dict)] if isinstance(reply.body.get("items"), list) else []
            rev = reply.body.get("rev") if isinstance(reply.body.get("rev"), int) else rev
            cursor = reply.body.get("next_cursor") if isinstance(reply.body.get("next_cursor"), str) else None
            if not cursor:
                break
        else:
            raise ArgentError("argent has more work items than one pull reads", 0, "too_many_pages")
        if await asyncio.to_thread(replace_all, tenant, rows, rev):
            resource_push.notify(topics.ARGENT_WORK_ITEMS)
        _pull.state = OK
    except Unauthorized:
        _pull.state = LOGIN_EXPIRED
    except (NotFound, Unreachable, ArgentError) as exc:
        logger.info("argent_work_items_pull_failed", error_type=type(exc).__name__, status=exc.status)
        _pull.state = UNAVAILABLE
    return _pull.state


def state() -> str:
    return _pull.state


def is_running() -> bool:
    return _pull.task is not None and not _pull.task.done()


async def _run() -> None:
    assert _pull.wake is not None
    while True:
        await pull_once()
        recent = _pull.viewed_at and time.monotonic() - _pull.viewed_at < VIEW_WINDOW
        try:
            await asyncio.wait_for(_pull.wake.wait(), FAST_SECONDS if recent else SLOW_SECONDS)
        except asyncio.TimeoutError:
            pass
        _pull.wake.clear()


def start() -> None:
    if is_running():
        return
    _pull.wake = asyncio.Event()
    _pull.task = asyncio.get_running_loop().create_task(_run())


async def stop() -> None:
    task, _pull.task = _pull.task, None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _pull.state, _pull.client, _pull.token = PENDING, None, None


def poke() -> None:
    if _pull.wake is not None:
        _pull.wake.set()
