
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from src.api import browser_routes
from src.api.auth import require_auth
from src.core import row_looks
from src.core.browser_pages import app_open, open_pages, page_tab, pool, resolvers, select
from src.core.browsers import store
from src.core.browsers.manager import BrowserUnavailable, CapReached
from src.cplugs.host import page_owner, runtime
from src.core.browsers.url_policy import UrlRefused, normalize_url, origin_of, storable_url
from src.models.browsers import BrowserInfo, CreateBrowserRequest, OpenPageRequest

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(require_auth)])

class _RowGone(LookupError):
    pass


def _normalized(url: str) -> str:
    try:
        return normalize_url(url)
    except UrlRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _artifact_tab(ref: Dict[str, Any]) -> Tuple[Dict[str, str], str]:
    try:
        resolved = await resolvers.resolve(page_tab.KIND_ARTIFACT, ref)
    except resolvers.PageKindUnavailable as exc:
        raise HTTPException(status_code=409, detail={
            "code": "browser_open_kind_unavailable", "detail": "huddle artifacts cannot be opened while the huddle is off"}) from exc
    except resolvers.PageNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "browser_open_not_found", "detail": "no such artifact"}) from exc
    return page_tab.artifact_page(resolved.path, ref["item"], ref["artifact"]), resolved.title




async def _reuse(browser_id: str, url: str, label: str, request: Request) -> BrowserInfo:
    manager = request.app.state.browser_manager
    row = await browser_routes.db_call(manager, store.update, browser_id, label=label, last_url=storable_url(url))
    if row is None:
        raise _RowGone(browser_id)
    try:
        live, relaunched = await manager.ensure_live(browser_id, url)
    except CapReached as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BrowserUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not relaunched:
        await live.navigate(url)
    return browser_routes.info_for(row, manager)


async def _try_reuse(browser_id: Optional[str], url: str, label: str, request: Request) -> Optional[BrowserInfo]:
    if browser_id is None:
        return None
    try:
        return await _reuse(browser_id, url, label, request)
    except _RowGone:
        pool.forget(browser_id)
        return None


async def open_in_pool(url: str, key: str, label: str, request: Request) -> BrowserInfo:
    for _ in range(pool.POOL_SIZE + 1):
        planned = pool.plan(key)
        if planned is None:
            break
        info = await _try_reuse(planned, url, label, request)
        if info is not None:
            pool.remember(info.id, key)
            return info
    try:
        info = await browser_routes.create_browser(CreateBrowserRequest(url=url, label=label), request)
    except HTTPException as exc:
        info = await _try_reuse(pool.fallback(), url, label, request) if exc.status_code == 409 else None
        if info is None:
            raise
    pool.remember(info.id, key)
    return info


@router.get("/browsers/selected")
async def get_selected() -> Dict[str, Any]:
    return {"select": select.current()}


async def _page_info(page: open_pages.OpenPage, src: Optional[str] = None) -> Dict[str, Any]:
    if src is None:
        src = page.src
    if src is None and page.ref is not None:
        try:
            src = (await resolvers.resolve(page_tab.KIND_ARTIFACT, page.ref)).path
        except (resolvers.PageNotFound, resolvers.PageKindUnavailable):
            src = None
    return app_open.page_info(page, src)


@router.get("/browsers/pages")
async def list_pages(request: Request) -> Dict[str, Any]:
    """
    Output: {pages: [{id, key, frame, title, opened_at, src, section}]}; ``section`` is the owning plugin's
      ``surfaces.page_section`` or None. A page whose plugin is off is left out and its row kept (``cplugs/host/page_owner.py``).
    """
    host = runtime.host_for(request.app)
    listed = []
    for page in open_pages.listing():
        owner = page_owner.owner_of(page.key)
        if owner is not None and not host.enabled(owner.id):
            continue
        info = await _page_info(page)
        info["section"] = (owner.manifest.surfaces.page_section or None) if owner is not None else None
        listed.append(info)
    return {"pages": listed}


@router.delete("/browsers/pages/{page_id}", status_code=204)
async def close_page(page_id: str) -> Response:
    """Close one page row (the frame goes with it on every window). Errors: 404 no such page."""
    if not open_pages.close(page_id):
        raise HTTPException(status_code=404, detail={"code": "browser_page_not_found", "detail": "no such page"})
    logger.info("browser_page_closed", page_id=page_id)
    return Response(status_code=204)


@router.post("/browsers/open")
async def open_page(body: OpenPageRequest, request: Request) -> Dict[str, Any]:
    if body.huddle_artifact is not None:
        ref = body.huddle_artifact.model_dump()
        page, own_title = await _artifact_tab(ref)
        stored = open_pages.open_page(page["key"], page["frame"], app_open.label_of(body.title, own_title), ref=ref, src=None)
        row_looks.apply_on_open(stored.id, body.color, body.icon)
        chosen = select.select_page(stored.id, stored.title)
        logger.info("browser_page_row_opened", kind=page["key"].split(":", 1)[0], frame=page["frame"])
        return {"page": await _page_info(stored, page["src"]), "select": chosen}
    if page_tab.is_app_path(body.url or ""):
        try:
            opened = app_open.open_app_page(body.url or "", body.title)
        except page_tab.AppPageRefused as exc:
            raise HTTPException(status_code=400, detail={"code": "browser_open_app_page", "detail": str(exc)}) from exc
        row_looks.apply_on_open(opened["page"]["id"], body.color, body.icon)
        logger.info("browser_page_row_opened", kind="app", frame=opened["page"]["frame"])
        return opened
    url = _normalized(body.url or "")
    info = await open_in_pool(url, pool.page_key("url", storable_url(url)), app_open.label_of(body.title, urlsplit(url).hostname or "browser"), request)
    row_looks.apply_on_open(info.id, body.color, body.icon)
    logger.info("browser_page_opened", browser_id=info.id, origin=origin_of(url), kind="url")
    return {"browser": info.model_dump(), "select": select.select(info.id, info.label)}
