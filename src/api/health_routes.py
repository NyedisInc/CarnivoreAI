
from fastapi import APIRouter, Request
from src.core.version import startup_version
from src.models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_endpoint(request: Request):
    """
    Health check endpoint for menu bar app.
    Returns server status, uptime, session info, and detected-server count.

    Note: This endpoint does NOT require authentication to allow menu bar app
    to poll before user logs in via web UI.

    Returns:
        Health status with stats
    """
    session_manager = request.app.state.session_manager
    local_servers = getattr(request.app.state, "local_servers", None)

    summary = session_manager.health_summary() if session_manager else None
    session_name, uptime_seconds = summary if summary else (None, 0)

    local_server_count = 0
    if local_servers is not None:
        try:
            local_server_count = sum(
                len(v) for v in local_servers.snapshot().values()
            )
        except Exception:
            local_server_count = 0

    return HealthResponse(
        status="running",
        uptime=uptime_seconds,
        session_name=session_name,
        local_server_count=local_server_count,
        version=startup_version(),
    )
