
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.cplugs.host import identity, runtime
from src.cplugs.host.preview_check import MEDIA_TYPES, PreviewError, read_preview
from src.cplugs.host.sidecar_manifest import VIEW_TYPES
from src.cplugs.host.sidecar_registry import SidecarDefinition
from src.cplugs.host.sidecar_routes import _LIVE_STATES, _error, held_off
from src.cplugs.sdk import signed_links
from src.cplugs.sdk.manifest import ID_PATTERN
from src.security_headers import OWN_POLICY_HEADER, build_view_csp

logger = structlog.get_logger()

TICKET_LABEL = "cplug-view-v1"
TICKET_TTL_S = 3600
MAX_FILE_BYTES = 2 * 1024 * 1024
VIEWS_FOLDER = "views"
_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_HOST = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:]+\](:\d{1,5})?$")
_DOCUMENT_DESTS = frozenset({"document", "iframe", "frame", "embed", "object"})

router = APIRouter(dependencies=[Depends(require_auth)], tags=["cplugs"])
public_router = APIRouter(tags=["cplugs"])


def _view_of(request: Request, cplug_id: str, name: str) -> Tuple[SidecarDefinition, dict, str]:
    host = runtime.host_for(request.app)
    d = runtime.find(cplug_id) if ID_PATTERN.match(cplug_id) else None
    view = next((v for v in d.manifest.views if v["name"] == name), None) if isinstance(d, SidecarDefinition) else None
    if view is None or runtime.hidden(d):
        raise _error(404, "cplug_unknown", "no such view")
    if not host.enabled(cplug_id):
        raise _error(409, "cplug_disabled", f"turn {cplug_id} on first")
    live = host.sidecar_runtime()
    if live is None:
        raise _error(503, "sidecar_runtime_unavailable", "the plugin runtime is not running")
    if any(live.safe_mode().values()) or live.supervisor.state(cplug_id) not in _LIVE_STATES:
        raise held_off(host, d, live)
    try:
        return d, view, host.install_key(cplug_id)
    except identity.LedgerUnreadable as exc:
        raise _error(503, "install_ledger_unreadable", "the install ledger could not be read") from exc


def _file(code_root: Path, name: str, view: dict, rel: str) -> Optional[bytes]:
    rel = rel or "index.html"
    if rel not in view["files"]:
        return None
    top = Path(code_root) / VIEWS_FOLDER / name
    node = top
    try:
        for part in rel.split("/"):
            node = node / part
            if node.is_symlink():
                return None
        if top.is_symlink() or not node.resolve().is_relative_to(top.resolve()):
            return None
        if not stat.S_ISREG(os.lstat(node).st_mode):
            return None
        fd = os.open(node, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as fh:
            st = os.fstat(fh.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_BYTES:
                return None
            return fh.read(MAX_FILE_BYTES + 1)[:MAX_FILE_BYTES]
    except OSError:
        return None


@router.get("/cplugs/{cplug_id}/preview")
async def preview_image(cplug_id: str) -> Response:
    """The plugin's declared preview image, re-checked on every read. Output: the bytes, a fixed image type from the sniffed format, ``nosniff``.

    Description: shown as the drawer thumbnail and the plugins page card, so it answers while the plugin is off too. The file is the manifest's ``preview``
      only (a path from the digest-pinned code root, no symlink, 512 KiB at most, hero header rules). Raises: 404 ``cplug_unknown`` (not a sidecar, hidden, none declared, or the file no longer passes).
    """
    d = runtime.find(cplug_id) if ID_PATTERN.match(cplug_id) else None
    if not isinstance(d, SidecarDefinition) or runtime.hidden(d) or not d.manifest.preview:
        raise _error(404, "cplug_unknown", "no preview")
    try:
        kind, body = await run_in_threadpool(read_preview, d.code_root, d.manifest.preview)
    except PreviewError as exc:
        logger.warning("cplug_preview_refused", cplug=cplug_id, reason=str(exc)[:120])
        raise _error(404, "cplug_unknown", "no preview") from exc
    return Response(content=body, media_type=MEDIA_TYPES[kind], headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-cache"})


@router.post("/cplugs/{cplug_id}/view/{name}/ticket")
async def view_ticket(cplug_id: str, name: str, request: Request) -> dict:
    """The path a frame loads for one view. Output: ``{path, expires_in}``; ``path`` is relative to the app origin and valid for an hour.

    Raises: 404 ``cplug_unknown``; 409 ``cplug_disabled``; 503. The page puts it in ``<iframe sandbox="allow-scripts" src>``.
    """
    d, _view, key = _view_of(request, cplug_id, name) if _NAME.match(name) else (None, None, "")
    if d is None:
        raise _error(404, "cplug_unknown", "no such view")
    ticket = signed_links.mint(TICKET_LABEL, [key, name], TICKET_TTL_S)
    return {"path": f"/api/v1/cplugs/{cplug_id}/view/{name}/{ticket}/index.html", "expires_in": TICKET_TTL_S}


@public_router.get("/cplugs/{cplug_id}/view/{name}/{ticket}/{rest:path}")
async def view_file(cplug_id: str, name: str, ticket: str, rest: str, request: Request) -> Response:
    """One declared file of a view, under the view's own policy. The ticket in the path is the credential (no bearer; an iframe cannot send one).

    Output: the file with its fixed content type, ``nosniff``, ``no-store`` and ``Content-Security-Policy`` from ``build_view_csp``.
    Raises: 404 (a bad or expired ticket, an undeclared view or file, a svg loaded as a page); 409 ``cplug_disabled``.
    """
    fields = signed_links.verify(TICKET_LABEL, ticket, 2) if _NAME.match(name) else None
    if fields is None or fields[1] != name:
        raise _error(404, "cplug_unknown", "no such view")
    d, view, key = _view_of(request, cplug_id, name)
    ext = (rest or "index.html").rsplit(".", 1)[-1]
    if fields[0] != key or ext not in VIEW_TYPES or (ext == "svg" and request.headers.get("sec-fetch-dest", "") in _DOCUMENT_DESTS):
        raise _error(404, "cplug_unknown", "no such view file")
    body = await run_in_threadpool(_file, d.code_root, name, view, rest)
    if body is None:
        raise _error(404, "cplug_unknown", "no such view file")
    netloc = request.url.netloc
    if not _HOST.match(netloc):
        raise HTTPException(status_code=400, detail={"code": "bad_host", "detail": "the Host header is not usable"})
    base = f"{request.url.scheme}://{netloc}/api/v1/cplugs/{cplug_id}/view/{name}/{ticket}/"
    return Response(content=body, media_type=VIEW_TYPES[ext],
                    headers={"Content-Security-Policy": build_view_csp(base), OWN_POLICY_HEADER: "1", "X-Content-Type-Options": "nosniff",
                             "Cache-Control": "no-store"})
