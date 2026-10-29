"""``/api/v1/browsers``: create, list, rename, navigate and close.

Thin: shape, auth, status codes and the connection dance. Launching and
stopping live in ``src/core/browsers/manager.py``, rows in ``store.py``,
the URL rule in ``url_policy.py``. See ``docs/browser-sessions.md``.

STATUS CODES. 400 a URL the policy refuses (the sentence says why). 404 an
id with no row (a malformed id is a 404 too, never a path). 409 the live
process cap (``browser.max_live``) is reached. 503 no usable Chromium, or
the datastore could not be read or written; a write that did not happen
never answers 2xx.
"""

from __future__ import annotations

from contextlib import closing
from typing import Callable, Optional, TypeVar
from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.core import resource_push, row_looks
from src.core.browsers import store
from src.core.resource_push.topics import BROWSERS as BROWSERS_TOPIC
from src.core.browsers.manager import BrowserManager, BrowserUnavailable, CapReached
from src.core.browsers.url_policy import UrlRefused, normalize_url, storable_url
from src.core.db import connect, db_path_for
from src.models.browsers import (
    BrowserInfo,
    BrowserList,
    CreateBrowserRequest,
    NavigateBrowserRequest,
    RenameBrowserRequest,
)

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(require_auth)])

T = TypeVar("T")


def _manager(request: Request) -> BrowserManager:
    return request.app.state.browser_manager


def info_for(row: store.BrowserRow, manager: BrowserManager) -> BrowserInfo:
    return BrowserInfo(
        id=row.id, label=row.label, url=row.last_url,
        state="live" if manager.is_live(row.id) else "stopped",
        viewers=manager.viewer_count(row.id),
        created_at=row.created_at, updated_at=row.updated_at,
    )


_ROW_WRITES = frozenset({store.insert, store.update, store.delete})


async def db_call(manager: BrowserManager, fn: Callable[..., T], *args, **kwargs) -> T:
    """Run one store function in ONE transaction on ONE worker thread.

    Inputs: manager (BrowserManager) - for its state dir; fn - a store
      function taking ``conn`` first; args / kwargs - the rest.
    Output: whatever ``fn`` returns.
    Raises: HTTPException 503 - the datastore could not be used.
    """
    def _run() -> T:
        with closing(connect(db_path_for(manager.state_dir), create=False)) as conn:
            with conn:
                return fn(conn, *args, **kwargs)

    try:
        result = await run_in_threadpool(_run)
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser_store_failed", op=fn.__name__, error=type(exc).__name__)
        raise HTTPException(status_code=503, detail="the datastore could not be used") from exc
    if fn in _ROW_WRITES:
        resource_push.notify(BROWSERS_TOPIC)
    return result


async def _row_or_404(manager: BrowserManager, browser_id: str) -> store.BrowserRow:
    row = await db_call(manager, store.get, browser_id) if store.is_valid_id(browser_id) else None
    if row is None:
        raise HTTPException(status_code=404, detail="no such browser session")
    return row


def _normalized(url: Optional[str]) -> str:
    try:
        return normalize_url(url)
    except UrlRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/browsers", response_model=BrowserList)
async def list_browsers(request: Request) -> BrowserList:
    """Every stored browser session with its live state."""
    manager = _manager(request)
    rows = await db_call(manager, store.list_all)
    return BrowserList(browsers=[info_for(r, manager) for r in rows])


@router.post("/browsers", response_model=BrowserInfo, status_code=201)
async def create_browser(body: CreateBrowserRequest, request: Request) -> BrowserInfo:
    """Launch a new browser session at ``url`` and store its row."""
    manager = _manager(request)
    url = _normalized(body.url)
    browser_id = store.new_id()
    try:
        await manager.launch(browser_id, url)
    except CapReached as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BrowserUnavailable as exc:
        await run_in_threadpool(store.delete_profile, manager.state_dir, browser_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    label = (body.label or "").strip() or urlsplit(url).hostname or "browser"
    try:
        row = await db_call(manager, store.insert, browser_id, label, storable_url(url))
    except HTTPException:
        await manager.stop(browser_id, "closed")
        await run_in_threadpool(store.delete_profile, manager.state_dir, browser_id)
        raise
    return info_for(row, manager)


async def _update_or_404(manager: BrowserManager, browser_id: str, **fields) -> store.BrowserRow:
    row = await db_call(manager, store.update, browser_id, **fields) if store.is_valid_id(browser_id) else None
    if row is None:
        raise HTTPException(status_code=404, detail="no such browser session")
    return row


@router.patch("/browsers/{browser_id}", response_model=BrowserInfo)
async def rename_browser(browser_id: str, body: RenameBrowserRequest, request: Request) -> BrowserInfo:
    """Change a browser session's label."""
    manager = _manager(request)
    row = await _update_or_404(manager, browser_id, label=body.label.strip() or "browser")
    return info_for(row, manager)


@router.post("/browsers/{browser_id}/navigate", response_model=BrowserInfo)
async def navigate_browser(browser_id: str, body: NavigateBrowserRequest, request: Request) -> BrowserInfo:
    """Send a live browser to ``url``; a stopped one reopens there."""
    manager = _manager(request)
    url = _normalized(body.url)
    row = await _update_or_404(manager, browser_id, last_url=storable_url(url))
    live = manager.live.get(browser_id)
    if live is not None:
        await live.navigate(url)
    return info_for(row, manager)


@router.delete("/browsers/{browser_id}", status_code=204)
async def close_browser(browser_id: str, request: Request) -> Response:
    """Delete the row, then stop the process and delete the profile (D6).

    Row first: a socket that opens during the close then gets 4404 instead
    of relaunching a browser whose profile is about to be removed.
    """
    manager = _manager(request)
    await _row_or_404(manager, browser_id)
    await db_call(manager, store.delete, browser_id)
    row_looks.forget(browser_id)
    try:
        await manager.discard(browser_id)
    except OSError as exc:
        logger.warning("browser_profile_delete_failed", browser_id=browser_id,
                       error=type(exc).__name__)
    return Response(status_code=204)
