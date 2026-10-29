
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from src.core.pack.identity.home import ProjectMovedAway
from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.config import settings
from src.core import debug_trace
from src.core.session_name_claim import sanitize_tmux_name
from src.models import ForkSessionResponse
from src.api.error_response import api_error, soft_failure

logger = structlog.get_logger()
router = APIRouter()


@router.post(
    "/sessions/{session_name}/fork",
    response_model=ForkSessionResponse,
    status_code=201,
    dependencies=[Depends(require_peer_sessions)],
)
async def fork_session(request: Request, session_name: str):
    """Fork a running session into a NEW tmux session that branches it.

    Description: spawns a new tmux session running the agent with
      ``--resume <uuid> --fork-session`` against the parent's Claude
      conversation, labels it with ``(fork)`` appended, and records
      ``parent_session_id`` on the CHILD row.

      THE PARENT IS NOT TOUCHED. Not archived, not stopped, not marked. It
      is still running, still listed, still resumable and still forkable
      again. There is no "was forked from" state because the process was
      never touched; the relationship is answered by a reverse lookup on
      ``parent_session_id``. See src/core/session_fork.py.

      THREE OUTCOMES, and the middle one is the point:
        404  no row for this tmux session - could not evaluate.
        409  the session has no recorded Claude conversation, so there is
             nothing to resume. REFUSED rather than forked, because
             forking anyway would start a brand new conversation wearing
             a "(fork)" label and the user would believe they had
             branched their work.
        201  forked. ``lineage_recorded`` says whether the parent link
             actually landed; the tmux session exists either way.
    Inputs: session_name (str) - the PARENT's tmux session name.
    Output: ForkSessionResponse.
    """
    from contextlib import closing

    from src.core import session_fork
    from src.core.db import DatastoreUnreadableError, connect, db_path_for

    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_name, "a fork")
    socket = session_manager.tmux_socket_name()
    db_path = db_path_for(settings.get_state_dir())

    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail="no datastore yet, so there is no session to fork from",
        )

    def _resolve():
        with closing(connect(db_path, create=False)) as conn:
            return session_fork.resolve_fork_source(
                conn, socket=socket, tmux_name=session_name
            )

    try:
        source = await run_in_threadpool(_resolve)
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, session=session_name) from exc

    if source.outcome == session_fork.FORK_UNRESOLVED:
        raise HTTPException(status_code=404, detail=source.detail or "session not found")
    if source.outcome == session_fork.FORK_NO_CONVERSATION:
        raise HTTPException(status_code=409, detail=source.detail or "nothing to resume")

    label = session_fork.fork_label(source.label)
    tmux_safe_name = sanitize_tmux_name(label) or label
    logger.info(
        "api_fork_session_request",
        parent=session_name,
        parent_id=source.parent_id,
        label=label,
    )

    from src.api.launch_profile_errors import refuse_gone_profile

    refuse_gone_profile(settings, source.agent_type, source.launch_record)
    debug_trace.trace(
        "fork.creating",
        parent=session_name,
        parent_id=source.parent_id,
        label=label,
        working_dir=source.working_dir,
        agent_type=source.agent_type,
        model=source.model,
    )
    try:
        forked = await session_fork.spawn_fork_child(
            session_manager,
            source={"working_dir": source.working_dir, "agent_type": source.agent_type, "model": source.model,
                    "id": source.parent_id},
            label=label,
            project_name=tmux_safe_name,
            agent_extra_args=session_fork.fork_arguments(source.claude_session_uuid),
            db_path=db_path,
            socket=socket,
        )
    except ProjectMovedAway:
        raise
    except Exception as exc:
        logger.warning(
            "fork_create_failed",
            parent=session_name,
            label=label,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        debug_trace.trace(
            "fork.create_failed",
            parent=session_name,
            label=label,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise api_error(500, "session_fork_failed", exc, parent=session_name, label=label) from exc

    child, recorded, detail = forked.session, forked.recorded, None
    if forked.stamp_error is not None:
        detail = soft_failure("fork_link_not_recorded", forked.stamp_error, status=500, parent=session_name)
    if not recorded and detail is None:
        detail = (
            "fork created, but its parent link could not be recorded; the "
            "session works and is simply not linked in the tree"
        )

    return ForkSessionResponse(
        success=True,
        session=child.model_dump() if hasattr(child, "model_dump") else {},
        parent_session_id=source.parent_id,
        lineage_recorded=recorded,
        detail=None if recorded else detail,
    )
