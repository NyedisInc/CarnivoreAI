
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.config import settings
from src.core import server_status
from src.core.tmux_backend import DEFAULT_SOCKET_NAME
from src.core.tmux_listing import coerce_listing

logger = structlog.get_logger()

router = APIRouter(tags=["server-status"])


def resolve_socket_name() -> str:
    try:
        return settings.load_auth_config().session.tmux_socket_name
    except (OSError, ValueError, AttributeError) as exc:
        logger.debug("server_status_socket_name_fallback", error=str(exc))
        return DEFAULT_SOCKET_NAME


def open_ids_by_name(session_manager: Any) -> Dict[str, str]:
    backends = session_manager._registry.backends
    mapping: Dict[str, str] = {}
    for session_id, backend in backends.items():
        name = getattr(backend, "tmux_session", None)
        if name:
            mapping[name] = session_id
    return mapping


def socket_drift_warnings(session_manager: Any) -> List[Dict[str, str]]:
    backends = session_manager._registry.backends
    if not backends:
        return []
    configured = resolve_socket_name()
    drifted: List[Dict[str, str]] = []
    for session_id, backend in backends.items():
        backend_socket = getattr(backend, "socket_name", None)
        if not backend_socket or backend_socket == configured:
            continue
        drifted.append(
            {
                "session_id": session_id,
                "tmux_session": getattr(backend, "tmux_session", "") or "",
                "backend_socket": backend_socket,
                "configured_socket": configured,
            }
        )
    if drifted:
        logger.warning(
            "tmux_socket_drift_detected",
            drifted=drifted,
            hint=(
                "a live session's backend socket no longer matches "
                "session.tmux_socket_name in config.json"
            ),
        )
    return drifted


def ownership_by_name(session_manager: Any) -> Dict[str, bool]:
    lister = getattr(session_manager, "list_attachable_sessions", None)
    if not callable(lister):
        return {}
    try:
        listing = coerce_listing(lister())
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("server_status_ownership_unavailable", error=str(exc))
        return {}
    if not listing.ok:
        logger.warning(
            "server_status_ownership_unavailable",
            reason=listing.reason,
            detail=listing.detail,
            note="every tmux row will report ownership as unknown",
        )
        return {}
    out: Dict[str, bool] = {}
    for row in listing.sessions:
        name = row.get("name")
        if name and "created_by_cloude" in row:
            out[name] = bool(row["created_by_cloude"])
    return out


@router.get(
    "/server/status",
    response_model=None,
    dependencies=[Depends(require_auth)],
)
async def get_server_status(request: Request) -> Dict[str, Any]:
    """Collect a read-only snapshot of the host, this process and tmux.

    Args:
        request: the incoming request, for ``app.state.session_manager``.

    Returns:
        The snapshot produced by :func:`src.core.server_status.collect`.
        Every section carries its own ``available``/``error`` pair so a
        probe that could not run renders as "cannot determine" rather
        than as a healthy zero.

    Raises:
        HTTPException: 503 when the session manager is not mounted, which
            is the only way the tmux rows could silently claim that no
            session belongs to this app.
    """
    session_manager: Optional[Any] = getattr(
        request.app.state, "session_manager", None
    )
    if session_manager is None:
        raise HTTPException(
            status_code=503, detail="session manager not available"
        )

    snapshot = server_status.collect(
        host=settings.host,
        port=settings.port,
        socket_name=resolve_socket_name(),
        ownership_by_name=ownership_by_name(session_manager),
        open_ids_by_name=open_ids_by_name(session_manager),
    )
    snapshot["socket_drift"] = socket_drift_warnings(session_manager)
    logger.info(
        "server_status_collected",
        tmux_running=snapshot["tmux"]["server_running"],
        session_count=len(snapshot["tmux"]["sessions"]),
        socket_drift_count=len(snapshot["socket_drift"]),
    )
    return snapshot
