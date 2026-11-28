
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from src.api.peer_auth import require_peer_sessions
from src.config import settings
from src.core import restart_inflight, restart_live_gate
from src.core.hosts.remote_restart import RemoteRestartRefused
from src.core.launch_profiles import create_seam
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.session_ops import restart as restart_ops
from src.models import RestartSessionResponse
from src.api.error_response import api_error, refusal_error, soft_failure

logger = structlog.get_logger()
router = APIRouter()


def _remote_error_to_http(exc: restart_ops.RemoteRestartFailed) -> HTTPException:
    cause = exc.__cause__
    if isinstance(cause, RemoteRestartRefused):
        return api_error(cause.status, cause.code or "remote_restart_refused", cause, host=exc.host)
    return refusal_error(cause, host=exc.host)


def restart_error_to_http(exc: Exception, session_uuid: str = "") -> HTTPException:
    if isinstance(exc, restart_inflight.RestartInFlightError):
        return api_error(409, restart_inflight.IN_PROGRESS_CODE, exc)
    if isinstance(exc, LaunchProfileNotFound):
        from src.api.launch_profile_errors import gone_profile_error  # noqa: PLC0415

        return gone_profile_error(exc, create_seam.known_pick_ids(settings))
    if isinstance(exc, restart_ops.RestartDatastoreUnreadable):
        return api_error(503, "datastore_unavailable", exc.__cause__ or exc, session_uuid=session_uuid)
    if isinstance(exc, (restart_ops.NoDatastore, restart_ops.RestartSourceNotFound)):
        return api_error(404, "not_found", exc)
    if isinstance(exc, restart_ops.AlreadyRunning):
        return api_error(409, restart_live_gate.ALREADY_RUNNING_CODE, exc)
    if isinstance(exc, restart_ops.ConversationOffloaded):
        return api_error(409, exc.body["code"], exc, extra=exc.body)
    if isinstance(exc, restart_ops.RowTakenOver):
        return api_error(409, "row_taken_over", exc, held_tmux_name=exc.held_tmux_name)
    if isinstance(exc, restart_ops.ConversationMissing):
        return api_error(409, "conflict", exc)
    if isinstance(exc, restart_ops.RemoteRestartFailed):
        return _remote_error_to_http(exc)
    context = exc.context if isinstance(exc, restart_ops.ReplacementCreateFailed) else {}
    return api_error(500, "session_restart_failed", exc.__cause__ or exc, **context)


@router.post(
    "/sessions/{session_uuid}/restart",
    response_model=RestartSessionResponse,
    status_code=201,
    dependencies=[Depends(require_peer_sessions)],
)
async def restart_session(request: Request, session_uuid: str):
    """Restart a stopped row onto its own conversation, refusing a second restart of it while one runs.

    Description: the HTTP face of ``session_ops.restart.restart_stopped_session``, which holds the per-row claim
      (src/core/restart_inflight.py), every gate and the spawn; this function only translates its typed errors with
      :func:`restart_error_to_http`. The row keeps its ``sessions.id`` and ``session_uuid``: a restart moves the record onto a new
      tmux instance and never inserts a second one (``session_restart.rebind_instance``).
    Inputs: request (Request); session_uuid (str) - the row's durable id.
    Output: RestartSessionResponse.
    Raises: HTTPException - 400, 404, 409, 500, 503 as :func:`restart_error_to_http` maps; a stopped remote row answers with its host's code.
    """
    def unconfirmed(exc: BaseException) -> str:
        return soft_failure("restart_record_unconfirmed", exc, status=500, session_uuid=session_uuid)

    try:
        return await restart_ops.restart_stopped_session(request.app.state, session_uuid, unconfirmed_note=unconfirmed)
    except restart_ops.RESTART_ERRORS as exc:
        raise restart_error_to_http(exc, session_uuid) from exc
