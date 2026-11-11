
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from typing import Any, List, Optional, Tuple

import structlog

from src.core.argent import settings as settings_module
from src.core.argent.client import ArgentClient, ArgentError, NotFound
from src.core.argent.runtime import get_runtime
from src.core.argent.store import open_db
from src.core.argent.upstream import NOT_READY_REASON, NOT_REGISTERED_REASON, _host

logger = structlog.get_logger()

ROUTE = "/v1/my/upstreams"
OK, MISSING = "ok", "missing"


def _key(tenant: str) -> str:
    return f"upstreams:{tenant}"


def _parse(body: Any) -> List[str]:
    rows = body.get("items") if isinstance(body, dict) else body
    return sorted({str(r["host"]).strip().lower() for r in (rows if isinstance(rows, list) else []) if isinstance(r, dict) and isinstance(r.get("host"), str) and r["host"].strip()})


def _save(tenant: str, state: str, hosts: List[str]) -> None:
    with closing(open_db()) as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (_key(tenant), json.dumps({"state": state, "hosts": hosts})))


def cached(tenant: str) -> Optional[Tuple[str, List[str]]]:
    if not tenant:
        return None
    try:
        with closing(open_db()) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (_key(tenant),)).fetchone()
        data = json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError) as exc:
        logger.warning("argent_upstreams_cache_unreadable", error_type=type(exc).__name__)
        return None
    return (str(data["state"]), list(data["hosts"])) if isinstance(data, dict) and "state" in data and isinstance(data.get("hosts"), list) else None


def verdict(copy: Optional[Tuple[str, List[str]]], url: str) -> str:
    if copy is None:
        return ""
    state, hosts = copy
    if state == MISSING:
        return NOT_READY_REASON
    return "" if _host(url) in hosts else NOT_REGISTERED_REASON


def reason_cached(tenant: str, url: str) -> str:
    return verdict(cached(tenant), url)


async def refresh(*, transport: Optional[Any] = None) -> Optional[Tuple[str, List[str]]]:
    cfg = settings_module.read()
    login = await asyncio.to_thread(get_runtime().store.get_login)
    token = get_runtime().tokens.read(str(login["tenant_id"])) if login else None
    if not cfg.server_url or not token:
        return None
    tenant = str(login["tenant_id"])
    try:
        reply = await ArgentClient(cfg.server_url, lambda: token, transport=transport).get(ROUTE)
        copy = (OK, _parse(reply.body))
    except NotFound:
        copy = (MISSING, [])
    except ArgentError as exc:
        logger.info("argent_upstreams_not_read", status=exc.status)
        return None
    try:
        await asyncio.to_thread(_save, tenant, *copy)
    except sqlite3.Error as exc:
        logger.warning("argent_upstreams_not_saved", error_type=type(exc).__name__)
    return copy


async def reason_live(tenant: str, url: str, *, transport: Optional[Any] = None) -> str:
    copy = await asyncio.to_thread(cached, tenant)
    if copy is None:
        copy = await refresh(transport=transport)
    return verdict(copy, url)
