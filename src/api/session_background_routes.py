
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import routed_remote
from src.api.session_name_known import known_tmux_names, strip_adopted_prefix
from src.api.themes_routes import _bundled_themes_root, _scan_both_roots, _user_themes_root
from src.core import terminal_background
from src.models import (
    SessionBackgroundEntry,
    SessionBackgroundsResponse,
    UpdateSessionBackgroundRequest,
)

logger = structlog.get_logger()
router = APIRouter()


def _store(request: Request):
    store = getattr(request.app.state, "session_background_store", None)
    if store is None:
        logger.error(
            "session_background_store_absent",
            reason="app assembled without a background override store",
        )
        raise HTTPException(
            status_code=503,
            detail="terminal background overrides are unavailable",
        )
    return store


def _entry_model(entry) -> SessionBackgroundEntry:
    return SessionBackgroundEntry(
        theme_id=entry.get("theme_id"),
        dim=entry.get("dim"),
        disabled=bool(entry.get("disabled")),
        image=entry.get("image"),
    )


@router.get(
    "/session-backgrounds",
    response_model=SessionBackgroundsResponse,
    dependencies=[Depends(require_auth)],
)
async def list_session_backgrounds(request: Request) -> SessionBackgroundsResponse:
    """Every per-session background override, plus the default scrim.

    The map is keyed on the bare tmux session name, the same key the theme
    pin uses. A session with no entry inherits whatever its resolved theme
    ships, which is the state every session starts in.
    """
    store = _store(request)
    return SessionBackgroundsResponse(
        overrides={
            name: _entry_model(entry) for name, entry in store.overrides.items()
        },
        default_dim=terminal_background.DEFAULT_DIM,
    )


async def _theme_ships_an_image(theme_id: str) -> bool:
    bundled_root = _bundled_themes_root()
    user_root = _user_themes_root()
    bundled, user = await asyncio.to_thread(
        _scan_both_roots, bundled_root, user_root
    )
    for manifest in list(bundled) + list(user):
        if manifest.id == theme_id:
            return manifest.background is not None
    return False


@router.patch(
    "/sessions/{session_name}/background",
    response_model=SessionBackgroundEntry,
    dependencies=[Depends(require_peer_sessions)],
)
async def set_session_background(
    request: Request, session_name: str, body: UpdateSessionBackgroundRequest
) -> SessionBackgroundEntry:
    """Set, change or clear one session's terminal background override.

    Body: ``{"theme_id": "<id>"|null, "dim": 0..1|null, "disabled": bool}``.

    All three at their defaults clears the override, dropping the session
    back to the image its resolved theme ships. ``disabled: true`` is the
    opposite request - paint nothing here even though the theme ships one -
    and it is stored, because absence already means inherit.

    ``dim`` is clamped rather than refused, matching every other number that
    arrives from a manifest or a control in this app. The clamp here is a
    bound at the trust boundary; the readability floor is derived from the
    theme's own palette in the client, where the palette is known, and it is
    always the binding one.
    """
    session_manager = request.app.state.session_manager
    remote = routed_remote(session_manager, session_name)
    owned_tmux = request.app.state.services.owned_tmux

    session_name = remote.key if remote else strip_adopted_prefix(session_name)
    if remote is None and session_name not in known_tmux_names(session_manager, owned_tmux):
        logger.info("session_background_set_404", session_name=session_name)
        raise HTTPException(
            status_code=404, detail=f"Unknown session {session_name!r}"
        )

    if body.theme_id and not await _theme_ships_an_image(body.theme_id):
        logger.info(
            "session_background_theme_has_no_image",
            session_name=session_name,
            theme_id=body.theme_id,
        )
        raise HTTPException(
            status_code=404,
            detail=(
                f"theme {body.theme_id!r} is not installed or ships no "
                f"background image"
            ),
        )

    store = _store(request)
    entry = store.set(
        session_name,
        theme_id=body.theme_id,
        dim=body.dim,
        disabled=body.disabled,
    )
    logger.info(
        "api_set_session_background",
        session_name=session_name,
        theme_id=body.theme_id,
        dim=body.dim,
        disabled=body.disabled,
        cleared=entry is None,
    )
    if entry is None:
        return SessionBackgroundEntry(theme_id=None, dim=None, disabled=False)
    return _entry_model(entry)
