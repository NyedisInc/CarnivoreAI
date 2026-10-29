
from __future__ import annotations


import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from src.api.auth import require_auth
from src.config import settings
from src.core.computers import membership
from src.core.setup_state import current_bind_report, current_setup_state

from src.api.shell.static import _render_index_html_response, client_dir

logger = structlog.get_logger()

router = APIRouter()


@router.get("/")
async def root(request: Request) -> Response:
    """Serve the web interface."""
    return _render_index_html_response(request)


@router.get("/session/{project}")
async def session_deep_link(project: str, request: Request) -> Response:
    """Serve the SPA shell for deep-link URLs.

    The ``project`` path parameter is consumed by the client-side router
    after the SPA boots; this handler does not inspect or validate it.
    """
    return _render_index_html_response(request)


@router.get("/layout/{layout_uuid}")
async def layout_deep_link(layout_uuid: str, request: Request) -> Response:
    """Serve the SPA shell for a saved Layout (issue #424); the client resolves the uuid."""
    return _render_index_html_response(request)


@router.get("/session")
async def session_empty(request: Request) -> Response:
    """Redirect a bare ``/session`` to the sessions view at ``/#sessions``."""
    return RedirectResponse(url="/#sessions", status_code=307)


@router.get("/archive")
async def archive_root_removed() -> RedirectResponse:
    """Send a visitor to the launchpad; the archive screen is gone.

    Output: RedirectResponse - 302 to "/".
    Example: GET /archive -> 302 Location: /
    """
    return RedirectResponse(url="/", status_code=302)


@router.get("/archive/{rest:path}")
async def archive_deep_link_removed(rest: str) -> RedirectResponse:
    """Send a deep-link visitor to the launchpad; the archive screen is gone.

    Inputs: rest (str) - the remainder of the archive path, ignored.
    Output: RedirectResponse - 302 to "/".
    Example: GET /archive/t/5767 -> 302 Location: /
    """
    return RedirectResponse(url="/", status_code=302)


@router.get("/api/v1/features")
async def features(_: str = Depends(require_auth)) -> JSONResponse:
    """Report the owner's UI flags.

    Description: the ``ui`` block is a plain boolean per surface, because these are the owner's own
      preferences. An unreadable config leaves each flag at its default, and the default is always
      "shown", so a failed read can never remove a control the user has.
    Inputs: none (auth required, same as every other /api/v1 route).
    Output: JSONResponse - {"ui": {show_mark_unread_control}}.
    Example: GET /api/v1/features -> {"ui": {"show_mark_unread_control": true}}
    """
    try:
        show_mark_unread = settings.load_auth_config().ui.show_mark_unread_control
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.warning("features_ui_flags_unreadable", error=str(exc))
        show_mark_unread = True
    return JSONResponse(content={"ui": {"show_mark_unread_control": show_mark_unread}})


_WEB_MANIFEST_PATH = client_dir / "manifest.webmanifest"
_APPLE_TOUCH_ICON_PATH = client_dir / "assets" / "icons" / "icon-180.png"
_SERVICE_WORKER_PATH = client_dir / "sw.js"


@router.get("/manifest.webmanifest")
async def web_manifest() -> FileResponse:
    """Serve the web app manifest from the origin root."""
    return FileResponse(
        _WEB_MANIFEST_PATH,
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.get("/sw.js")
async def push_service_worker() -> FileResponse:
    """Serve the push-only service worker from the origin root (issue #164). Never cached: a new worker must win."""
    return FileResponse(
        _SERVICE_WORKER_PATH,
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.get("/apple-touch-icon.png")
async def apple_touch_icon() -> FileResponse:
    """Serve the 180px home-screen icon for iOS's root-path probe."""
    return FileResponse(_APPLE_TOUCH_ICON_PATH, media_type="image/png")


@router.get("/health", response_model=None)
async def health_check(request: Request) -> dict[str, object]:
    """Health check endpoint.

    Also reports the exposure in force, because the menu bar has to show the
    address the server is ACTUALLY on. Reading the configured value and
    displaying that would show an aspiration as a fact - the exact thing the
    bind lockdown makes possible, since a locked-down server is not on the
    address its own configuration names.

    This endpoint is unauthenticated, and reporting the bind here does not
    leak anything: whoever is reading the response already reached the socket.

    Returns:
        The usual health fields plus ``bind``: the effective and configured
        addresses, whether the lockdown is in force, and whether a restart is
        needed before the configured address applies.
    """
    setup_state = current_setup_state()
    return {
        "status": "healthy",
        "session_active": _manager.health_summary() is not None if (_manager := getattr(request.app.state, "session_manager", None)) else False,
        "monitoring": _monitor.is_monitoring if (_monitor := getattr(request.app.state, "log_monitor", None)) else False,
        "setup_status": setup_state.status,
        "joined": setup_state.joined,
        "rebind_requested": membership.rebind_requested(),
        "door_file": getattr(request.app.state, "door_file_name", None),
        "bind": current_bind_report(),
    }

