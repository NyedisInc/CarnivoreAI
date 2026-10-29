"""The catalog hero image, served same-origin to the signed-in app (S2 of #1342).

``GET /api/v1/catalog/media/{sha256}`` answers ONLY a hash the current
VERIFIED index names (404 for every other, so this is not a fetch proxy),
fetches it from the index host once, verifies sha-256 and the WebP magic
before writing it under the state directory, and serves it as
``image/webp`` with ``nosniff``. The page paints it through an object URL
(the CSP already allows ``blob:``), because an ``<img>`` cannot carry the
bearer header.

REGISTRATION ORDER IS LOAD BEARING: BEFORE ``catalog_routes`` in
``src/api/routes.py``, whose greedy ``:path`` converter would swallow it.
"""

from __future__ import annotations

import asyncio
import hashlib
import weakref
from typing import Union

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from src.api.auth import require_auth
from src.core.catalog import client as catalog_client
from src.core.catalog import media
from src.core.catalog.fetch_stream import FetchRefusal
from src.models.catalog_media import MEDIA_SHA_RE

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])

_locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=31536000, immutable",
}


@router.get("/catalog/media/{sha256}", dependencies=[Depends(require_auth)])
async def get_catalog_media(sha256: str, request: Request) -> Response:
    """One hero image, by the sha-256 the verified index names.

    Inputs: sha256 (str) - 64 lowercase hex; request (Request).
    Output: Response - the webp bytes.
    Raises: HTTPException(404) for a hash the verified index does not
      name (or a malformed one); 502 when the image host fails or the
      bytes are not the named image.
    """
    if not MEDIA_SHA_RE.match(sha256):
        raise HTTPException(status_code=404, detail="no such media")
    services = request.app.state.services
    snapshot = await services.catalog.index_cache.get()
    keep = media.referenced_shas(snapshot.verified)
    if sha256 not in keep:
        raise HTTPException(status_code=404, detail="no such media")
    state_dir = services.settings_reader.state_dir()
    path = media.store_path(state_dir, sha256)
    lock = _locks.get(sha256)
    if lock is None:
        lock = _locks[sha256] = asyncio.Lock()
    async with lock:
        body = await _stored_or_fetched(request, state_dir, path, sha256, keep)
    return Response(content=body, media_type="image/webp", headers=_HEADERS)


async def _stored_or_fetched(
    request: Request, state_dir, path, sha256: str, keep: set
) -> bytes:
    try:
        if path.is_file():
            stored = await asyncio.to_thread(path.read_bytes)
            if hashlib.sha256(stored).hexdigest() == sha256:
                return stored
            logger.warning("catalog_media_stored_mismatch", sha256=sha256)
            await asyncio.to_thread(path.unlink, missing_ok=True)
        services = request.app.state.services
        client = await catalog_client.shared_client()
        body: Union[bytes, FetchRefusal] = await media.fetch_media(
            client, services.catalog.index_url(), sha256
        )
        if isinstance(body, FetchRefusal):
            raise HTTPException(
                status_code=502, detail={"code": body.code, "detail": body.detail}
            )
        await asyncio.to_thread(media.save_media, state_dir, sha256, body, keep)
        return body
    except OSError as exc:
        logger.warning("catalog_media_store_failed", error=str(exc))
        raise HTTPException(status_code=502, detail="media store unavailable") from exc
