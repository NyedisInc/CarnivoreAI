
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.catalog_views import (
    find_item,
    index_status,
    item_view,
    item_views,
    ledger_rows_by_item,
)
from src.core import resource_push
from src.core.catalog.fetch_stream import FetchRefusal
from src.core.catalog.index_cache import IndexSnapshot
from src.core.resource_push import topics as resource_topics
from src.models.catalog_api import (
    CatalogItemResponse,
    CatalogListResponse,
    IndexStatus,
    RevocationsRefreshResponse,
)

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])


def refuse_empty(snapshot: IndexSnapshot) -> None:
    if snapshot.verified is not None or snapshot.refusal is None:
        return
    refusal = snapshot.refusal
    if isinstance(refusal, FetchRefusal):
        raise HTTPException(
            status_code=502,
            detail={"code": refusal.code, "detail": refusal.detail},
        )
    raise HTTPException(
        status_code=409,
        detail={"code": refusal.code, "detail": refusal.detail},
    )


async def _snapshot(request: Request) -> IndexSnapshot:
    catalog = request.app.state.services.catalog
    return await catalog.index_cache.get()


@router.get(
    "/catalog/items",
    response_model=CatalogListResponse,
    dependencies=[Depends(require_auth)],
)
async def list_catalog_items(request: Request) -> CatalogListResponse:
    """Every item the held index carries, with what is installed joined on.

    Returns the index's own state, the installable items, and the items
    whose publisher key this app does not pin. The second list is never
    hidden: a user who can see an untrusted entry can see why it cannot
    be installed.

    Raises:
        HTTPException(502): nothing is held and the catalog was not
            reached.
        HTTPException(409): nothing is held and the bytes were refused.
    """
    services = request.app.state.services
    snapshot = services.catalog.index_cache.snapshot()
    refuse_empty(snapshot)

    with services.catalog.ledger() as ledger:
        rows = ledger_rows_by_item(ledger.list())

    verified = snapshot.verified
    items = () if verified is None else verified.items
    untrusted = () if verified is None else verified.untrusted_items
    return CatalogListResponse(
        index=index_status(snapshot),
        items=item_views(
            items, rows=rows, snapshot=snapshot, untrusted=False, cache=services.catalog.index_cache
        ),
        untrusted=item_views(
            untrusted, rows=rows, snapshot=snapshot, untrusted=True, cache=services.catalog.index_cache
        ),
    )


@router.get(
    "/catalog/items/{item_id:path}",
    response_model=CatalogItemResponse,
    dependencies=[Depends(require_auth)],
)
async def get_catalog_item(request: Request, item_id: str) -> CatalogItemResponse:
    """One item by its ``<publisher>/<name>`` id.

    The id carries a slash, so the path converter is ``:path``. An
    untrusted item is returned rather than hidden, carrying
    ``untrusted: true``; the install path is what refuses it.

    Raises:
        HTTPException(404): the held index carries no such item.
        HTTPException(502): nothing is held and the catalog was not
            reached.
        HTTPException(409): nothing is held and the bytes were refused.
    """
    services = request.app.state.services
    snapshot = await _snapshot(request)
    refuse_empty(snapshot)

    item, untrusted = find_item(snapshot, item_id)
    if item is None:
        raise HTTPException(
            status_code=404, detail=f"no catalog item {item_id!r}"
        )

    with services.catalog.ledger() as ledger:
        rows = ledger_rows_by_item(ledger.list())

    return CatalogItemResponse(
        index=index_status(snapshot),
        item=item_view(
            item,
            installed=rows.get(item.id),
            snapshot=snapshot,
            untrusted=untrusted,
            cache=services.catalog.index_cache,
        ),
    )


@router.get(
    "/catalog/index/status",
    response_model=IndexStatus,
    dependencies=[Depends(require_auth)],
)
async def catalog_index_status(request: Request) -> IndexStatus:
    """What this server believes about the index, without forcing a fetch.

    A refusal is a FIELD here, never a status code: this endpoint's whole
    job is to report the state including the bad ones, so answering 502
    would leave a client unable to ask "what is wrong" without handling
    an error.
    """
    return index_status(await _snapshot(request))


@router.post(
    "/catalog/refresh",
    response_model=IndexStatus,
    dependencies=[Depends(require_auth)],
)
async def refresh_catalog_on_open(request: Request) -> IndexStatus:
    """The catalog screen opened: refresh the index if it has not been lately.

    Debounced by the index cache's five minute throttle, which a refusal
    advances too, so a screen opened ten times in a minute, or against a
    host that is down, costs one round trip. ``refreshed`` says whether this
    call attempted one. A changed catalog reaches clients as the ``catalog``
    topic, not through this response.
    """
    catalog = request.app.state.services.catalog
    snapshot, refreshed = await catalog.index_cache.refresh_if_due()
    refresher = getattr(request.app.state, "catalog_index_refresher", None) or getattr(catalog, "index_refresher", None)
    if refresher is not None and snapshot.verified is not None and snapshot.refusal is None:
        await refresher.notify_after_pass(snapshot)
    status = index_status(snapshot)
    status.refreshed = refreshed
    return status


@router.post(
    "/catalog/index/refresh",
    response_model=IndexStatus,
    dependencies=[Depends(require_auth)],
)
async def refresh_catalog_index(request: Request) -> IndexStatus:
    """Fetch the index now, ignoring the five minute throttle.

    The only caller that forces. A refusal is reported in the returned
    block rather than raised, for the same reason the status endpoint
    does it: the user pressed refresh and is owed the answer, including
    "it did not work and here is the code".

    FORCING SKIPS THE THROTTLE, NOT EVERY FLOOR. A burst arriving inside
    ``FORCE_REFRESH_FLOOR_SECONDS`` of the last round trip is answered
    from the held snapshot with ``refreshed: false``, because a held
    button must not become an unbounded fan-out at the catalog host, and
    because saying "refreshed" when nothing was fetched is a lie the
    client cannot detect.
    """
    catalog = request.app.state.services.catalog
    snapshot, refreshed = await catalog.index_cache.refresh_now()
    refresher = getattr(request.app.state, "catalog_index_refresher", None) or getattr(catalog, "index_refresher", None)
    if refresher is not None and snapshot.verified is not None and snapshot.refusal is None:
        await refresher.notify_after_pass(snapshot)
    logger.info(
        "catalog_index_refresh_requested",
        held=snapshot.verified is not None,
        refreshed=refreshed,
        refused=None if snapshot.refusal is None else snapshot.refusal.code,
    )
    status = index_status(snapshot)
    status.refreshed = refreshed
    return status


@router.post(
    "/catalog/revocations/refresh",
    response_model=RevocationsRefreshResponse,
    dependencies=[Depends(require_auth)],
)
async def refresh_catalog_revocations(request: Request) -> RevocationsRefreshResponse:
    """Force an immediate index/revocation sync and stop any revoked sidecar plugins."""
    import asyncio

    catalog = request.app.state.services.catalog
    snapshot, refreshed = await catalog.index_cache.refresh_now()
    refresher = getattr(request.app.state, "catalog_index_refresher", None) or getattr(catalog, "index_refresher", None)
    if refresher is not None and snapshot.verified is not None and snapshot.refusal is None:
        await refresher.notify_after_pass(snapshot)
    revoked_keys: frozenset = frozenset()
    revoked_versions: frozenset = frozenset()
    if snapshot.verified is not None:
        revoked_keys, revoked_versions = await asyncio.to_thread(
            catalog.index_cache.revoked_sets, snapshot.verified
        )
    resource_push.notify(resource_topics.CATALOG)
    resource_push.notify("cplugs")
    verified = snapshot.verified
    return RevocationsRefreshResponse(
        serial=None if verified is None else verified.serial,
        generated_at=None if verified is None else verified.generated_at.isoformat(),
        revoked_keys=sorted(revoked_keys),
        revoked_versions=sorted(revoked_versions),
        refreshed=refreshed,
    )
