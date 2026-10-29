
import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from src.api.auth import require_auth
from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.api.uploads import save_upload_to_session_dir, validate_upload
from src.config import settings
from src.models import CommandRequest, SuccessResponse, UploadImageResponse
from typing import Optional

logger = structlog.get_logger()
router = APIRouter()


async def _refuse_open_dialog(request: Request) -> Optional[str]:
    from src.core.approvals.dialog_gate import CLEAR, OPEN, dialog_verdict

    session_id = request.app.state.services.registry.resolve_session_id(None)
    if session_id is None:
        return None
    verdict = await dialog_verdict(request.app, session_id)
    if verdict == CLEAR:
        return session_id
    code = "pane_dialog_open" if verdict == OPEN else "dialog_unreadable"
    logger.info("api_send_command_refused", session_id=session_id, code=code)
    raise HTTPException(status_code=409, detail={"code": code})


@router.post("/sessions/command", response_model=SuccessResponse, dependencies=[Depends(require_auth)])
async def send_command(request: Request, body: CommandRequest):
    """
    Send a command to the active session.

    Args:
        body: Command to send

    Returns:
        Success response

    Raises:
        HTTPException: 409 ``pane_dialog_open`` or ``dialog_unreadable`` (nothing written); 404 no session; 500.
    """
    session_manager = request.app.state.session_manager
    checked_id = await _refuse_open_dialog(request)

    try:
        logger.info("api_send_command", length=len(body.command))

        await session_manager.send_command(body.command, session_id=checked_id)

        return SuccessResponse(message="Command sent successfully")

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("send_command_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to send command: {str(e)}")


@router.post(
    "/sessions/upload-file",
    response_model=UploadImageResponse,
    status_code=201,
    dependencies=[Depends(require_peer_sessions)],
)
@router.post(
    "/sessions/upload-image",
    response_model=UploadImageResponse,
    status_code=201,
    dependencies=[Depends(require_peer_sessions)],
    include_in_schema=False,
)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    session_id: Optional[str] = None,
):
    """Persist an uploaded file into a session's upload bucket.

    Accepts ANY file, not only images: the point of the feature is to hand
    Claude a path to something it can read for itself. Images keep the
    stricter contract (magic-byte cross-check, tighter size cap); everything
    else is size-capped and name-sanitised but its bytes are never parsed.
    See ``src/api/uploads.py`` for the full validation contract.

    The validated file is written to
    ``<working_dir>/.cloude_uploads/<uuid8>-<safe_name>`` with mode 0o600
    (directory 0o700), via ``O_EXCL`` so nothing is silently overwritten. The
    client then injects the returned absolute ``path`` into the terminal.

    TWO PATHS, ONE HANDLER. ``/sessions/upload-file`` is the canonical route.
    ``/sessions/upload-image`` is retained (and hidden from the schema)
    because this is a PWA: a browser holding a cached older ``api.js`` would
    otherwise 404 on every paste until its service worker updated.

    ``session_id`` (query, optional) picks which session's working dir to
    write into; omitted uses the current session. The terminal tab that's
    pasting passes its own session id so the file lands in the right project.

    Raises:
        HTTPException: 409 if no matching session, 400 on validation failure
            (oversize, empty, or an image failing its magic-byte check), 500
            on disk error.
    """
    session_manager = request.app.state.session_manager

    from_peer = getattr(request.state, "peer_grant", None) is not None
    if from_peer and not session_id:
        raise HTTPException(status_code=400, detail="a session id is required")
    registry = request.app.state.services.registry
    session = registry.get_session(session_id) if session_id else None
    if from_peer and session is None:
        raise HTTPException(status_code=404, detail="no such session")
    if session is None:
        if not session_manager.has_active_session():
            raise HTTPException(status_code=409, detail="No active session to upload into")
        session = registry.current_session()
    if session is None or not session.working_dir:
        raise HTTPException(status_code=409, detail="Active session has no working directory")
    refuse_remote(session_manager, session.id, "a file upload")

    declared_filename = file.filename or ""
    data = await file.read()

    logger.info(
        "api_upload_file_request",
        declared_filename=declared_filename,
        size=len(data),
        content_type=file.content_type,
    )

    uploads_cfg = settings.load_auth_config().uploads
    validated_bytes, safe_name = validate_upload(
        data,
        declared_filename,
        uploads_cfg.max_size_mb,
        uploads_cfg.max_file_size_mb,
    )

    try:
        target_path = save_upload_to_session_dir(
            validated_bytes, safe_name, session.working_dir
        )
    except HTTPException:
        raise
    except OSError as e:
        logger.error("upload_file_save_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    logger.info(
        "api_upload_file_saved",
        path=str(target_path),
        size=len(validated_bytes),
    )

    return UploadImageResponse(
        path=str(target_path),
        filename=target_path.name,
        size=len(validated_bytes),
    )
