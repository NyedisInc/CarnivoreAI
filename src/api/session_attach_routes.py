
import asyncio
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from src.core.pack.identity.home import ProjectMovedAway
from src.api.auth import require_auth
from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.api.resize_negotiation import adopt_grid
from src.config import settings
from src.core.hosts.registry import HostUnavailable
from src.core.swarm import leaders as swarm_leaders
from src.core.swarm import switch as swarm_switch
from src.core.launch_profiles import create_seam
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.launch_profiles.secrets import SecretError
from src.core.tmux_listing import coerce_listing
from src.models import (
    AdoptSessionRequest,
    AdoptSessionResponse,
    AttachableListingStatus,
    AttachableSession,
    RespawnSessionRequest,
    RespawnSessionResponse,
    SuccessResponse,
)
from typing import Any, List, Optional

logger = structlog.get_logger()
router = APIRouter()


@router.get(
    "/sessions/attachable",
    response_model=List[AttachableSession],
    dependencies=[Depends(require_auth)],
)
async def list_attachable_sessions(request: Request):
    """List tmux sessions on our socket that are available for adoption.

    Excludes the currently-active backend's session name so the UI never
    offers self-adopt as a valid action (the client also filters defensively).
    Each row carries ``created_by_cloude`` sourced from the SessionManager's
    persisted ``owned_tmux_sessions`` set - not a spoofable prefix match.

    THREE OUTCOMES, NOT TWO. A 200 with ``[]`` means tmux was asked and
    genuinely has no adoptable sessions. When the probe could not run at
    all this returns **503** with an ``AttachableListingStatus`` detail
    rather than an empty 200, because an empty 200 is a claim we have no
    evidence for and the client cannot tell the two apart. Every existing
    JS consumer already treats a thrown call as "not proof the session is
    gone" (see ``terminal.js::_attemptReconnectByName``), so the failure
    is honest at the wire and safe at the callers.

    Inputs:
        request: the incoming request, for ``app.state.session_manager``.

    Output:
        List[AttachableSession]: adoptable rows, self-adopt filtered out.

    Raises:
        HTTPException: 503 when the tmux listing could not be determined.
    """
    return await asyncio.to_thread(attachable_rows, request.app.state.session_manager)


def attachable_rows(session_manager: Any) -> List[dict]:
    """The ``/sessions/attachable`` body: adoptable tmux rows, self-adopt filtered.

    Description: the one assembly of this listing; the route answers from
      it and the listing push builds its ``attachable`` collection from it.
    Inputs: session_manager (Any) - the app's SessionManager.
    Output: list[dict] - adoptable rows.
    Raises: HTTPException 503 - the tmux listing could not be determined.
    Example: rows = attachable_rows(request.app.state.session_manager)
    """
    listing = coerce_listing(session_manager.list_attachable_sessions())
    if not listing.ok:
        logger.warning(
            "attachable_route_listing_unavailable",
            reason=listing.reason,
            detail=listing.detail,
        )
        raise HTTPException(
            status_code=503,
            detail=AttachableListingStatus(
                listing_reason=listing.reason or "probe_error",
                listing_detail=listing.detail,
            ).model_dump(),
        )
    sessions = [
        {**row, **listing.row_status_payload()} for row in listing.sessions
    ]

    active_names = session_manager.active_tmux_names()
    if active_names:
        sessions = [s for s in sessions if s.get("name") not in active_names]

    return sessions


@router.post(
    "/sessions/adopt",
    response_model=AdoptSessionResponse,
    dependencies=[Depends(require_auth)],
)
async def adopt_session(request: Request, body: AdoptSessionRequest):
    """Adopt an externally-started tmux session as a new concurrent session.

    Multi-session: this never detaches another session, and it does not
    return 409 for a concurrency conflict - multiple adopted/owned sessions
    coexist. ``confirm_detach`` in the body is accepted for API back-compat
    and ignored.

    S7 - THIS ROUTE NOW PERSISTS THE ADOPTION. ``sessions.origin`` moves to
    ``adopted`` on the row keyed by the tmux instance triple, so the claim
    survives an app restart, a server restart and a reboot. Both ``created``
    and ``adopted`` badge as OURS; ``observed`` is the only external value,
    and which of the two a session was stays visible in the detail view.

    THREE OUTCOMES, NOT TWO. A session that DIED between the client's
    listing and this call matches zero rows. That is neither success nor a
    server fault, so it is neither a 200 nor a 500: it returns **409** with
    ``error='session_gone'`` and ``refresh=True``, and NO ROW IS MARKED
    ADOPTED. An empty 200 would badge a corpse as the user's, and a 500
    would blame the server for a normal, expected race. A probe that could
    not run at all is a different answer again and never renders as gone -
    the adoption proceeds and the failure to record it is logged.

    A PANE THE ``#{pane_dead}`` PROBE MEASURED DEAD IS THE SAME OUTCOME.
    ``remain-on-exit`` keeps a husk on the socket, so the listing above can
    still name it and the click can still reach ``attach_existing`` before
    the probe there catches it - a later measurement of the same "gone"
    fact, answered the same way: 409, ``session_gone``, ``refresh=True``.
    Other failures (the pane-dead probe itself failing to run, tmux not
    running, unsafe session name) propagate as 500 via the app's error
    middleware; we deliberately do NOT wrap them here, because not having
    measured death is not evidence of it.

    Raises:
        HTTPException: 409 when the target session is no longer there,
            whether that was read off the listing or measured on the pane.
    """
    from src.core.session_adopt_persist import AdoptTargetGoneError

    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, body.session_name, "an adopt")

    logger.info(
        "api_adopt_session_request",
        session_name=body.session_name,
        confirm_detach=body.confirm_detach,
    )

    services = getattr(request.app.state, "services", None)
    ids = services.registry.registered_ids_for_tmux_name(body.session_name) if services else []
    cols, rows = adopt_grid(session_manager, ids, body.cols, body.rows)
    try:
        result = await session_manager.adopt_external_session(
            name=body.session_name,
            confirm_detach=body.confirm_detach,
            initial_cols=cols,
            initial_rows=rows,
        )
    except AdoptTargetGoneError as exc:
        logger.warning(
            "api_adopt_session_gone",
            session_name=body.session_name,
            detail=str(exc),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "session_gone",
                "session_name": body.session_name,
                "message": str(exc),
                "refresh": True,
            },
        )

    from src.core.session_status_seed_read import seed_live_sessions

    seed_live_sessions(session_manager)

    return AdoptSessionResponse(**result)


@router.post(
    "/sessions/respawn",
    response_model=RespawnSessionResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def respawn_session(request: Request, body: RespawnSessionRequest):
    """Restart the agent inside a session whose process has exited.

    The counterpart to ``DELETE /sessions/external/{name}``: that one
    throws the corpse away, this one revives it. ``remain-on-exit`` keeps
    the pane, its id, its scrollback and this app's ``pipe-pane`` alive
    when the agent exits, so nothing here creates a session - it puts a
    process back into the one that is already there. The session's row,
    project attribution, pinned theme, unread state and name all survive
    because the instance triple they are keyed on does not change, and
    this path issues no database write at all.

    NOT A FORK. A fork mints a new ``sessions`` row and sets
    ``parent_session_id`` / ``fork_kind``. A respawn cannot mint one -
    ``#{session_created}`` is unchanged, so there is no new instance for a
    row to key on - and it never writes either column.

    NO COMMAND CROSSES THIS BOUNDARY. The body carries a session name and
    optionally an ``agent_type``. What gets run is decided server-side by
    the ladder in ``src.core.session_respawn``, gated on tmux's own
    ``#{pane_start_command}``. Accepting a command from the client would
    make this a create wearing a restart's clothes.

    REPLACING WHAT IS RUNNING IS A SEPARATE, EXPLICIT REQUEST.
    ``confirm_restart_live`` is what turns this into ``respawn-pane -k``:
    the pane's process is killed and a new one started in the same pane,
    keeping the tmux name, the ``sessions`` row and therefore the project
    attribution, pinned theme, unread state, group filing and sidebar
    position - nothing is re-carried because nothing moves.

    IT IS A PERMISSION AND ONLY THE CLIENT CAN GRANT IT. The preview's
    ``projected`` rung says what a live session would come back AS, and
    that is a PREDICTION: it cannot be echoed back as this flag, and the
    server derives the flag from nothing. Without it a live pane still
    answers ``kind='not_dead'`` and tmux itself refuses the respawn.

    ASK BEFORE YOU ACT. ``GET /sessions/restart/preview``
    (``src/api/restart_routes.py``) reports which rung this session would
    land on, for every configured wrapper, without spawning anything.
    That is what lets a client warn that an empty ``pane_start_command``
    means a plain restart returns a LOGIN SHELL.

    WHY A REFUSAL IS STILL A 200. ``ok=false`` with
    ``kind='cannot_determine'`` means the SERVER worked perfectly and the
    PANE could not be read. A 500 there would blame the server for a state
    it correctly detected, and would push the client into an error path
    instead of showing the user the sentence that says what is unknown.
    The only 4xx here is a name tmux would misread as a target.

    Raises:
        HTTPException(400): the name contains ``:`` or ``.``.
        HTTPException(500): a genuine, unexpected server fault.
    """
    session_manager = request.app.state.session_manager

    logger.info(
        "api_respawn_session_request",
        name=body.session_name,
        agent_type=body.agent_type,
        confirm_restart_live=bool(body.confirm_restart_live),
    )

    result = await respawn_or_http(
        session_manager,
        body.session_name,
        agent_type=body.agent_type,
        live_restart_confirmed=bool(body.confirm_restart_live),
        account_id=body.account_id,
        account_pinned=body.account_pinned,
    )
    return RespawnSessionResponse(**result)


async def respawn_or_http(session_manager: Any, name: str, **kwargs: Any) -> dict:
    try:
        return await session_manager.respawn_session(name, **kwargs)
    except LaunchProfileNotFound as exc:
        logger.warning("respawn_launch_profile_missing", name=name, profile=exc.profile_id)
        raise HTTPException(status_code=400, detail={
            "code": exc.codes[0], "codes": list(exc.codes), "detail": str(exc),
            "wrapper_options": create_seam.known_pick_ids(settings),
        })
    except SecretError as exc:
        logger.warning("respawn_launch_secret_unavailable", name=name, error=str(exc))
        raise HTTPException(status_code=409, detail={"code": "launch_secret_unavailable", "detail": str(exc)})
    except ProjectMovedAway:
        raise
    except swarm_switch.BodyHeld:
        raise HTTPException(status_code=409, detail=swarm_switch.refusal())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("respawn_session_failed", name=name, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restart session {name!r}: {exc}",
        )


@router.delete(
    "/sessions/external/{name}",
    response_model=SuccessResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def destroy_external_session(request: Request, name: str, confirm_name: Optional[str] = None):
    """Destroy an external (non-active) tmux session by name.

    The launchpad's "X" button on a non-active running-session row used
    to call adopt-then-destroy, which 500'd whenever the target pane was
    dead (foreground process exited). This endpoint kills the tmux
    session directly via ``tmux -L <socket> kill-session -t <name>``,
    skipping adoption - so dead-pane sessions can still be cleaned up.

    Returns:
        SuccessResponse. ``message`` indicates whether the session was
        actually killed or was already gone.

    Raises:
        HTTPException(400): name is unsafe (contains ``:`` or ``.``) OR
            name matches the currently-active session (use
            ``DELETE /sessions`` for that).
        HTTPException(409): ``leader_protected``, a Swarm leader's body without its exact ``confirm_name`` (query).
        HTTPException(500): genuine tmux failure.
    """
    session_manager = request.app.state.session_manager
    await swarm_leaders.require_confirm(tmux_name=name, confirm_name=confirm_name)

    logger.info("api_destroy_external_session_request", name=name)

    try:
        result = await session_manager.destroy_external_session(name)
    except HostUnavailable as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "detail": str(e)})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "external_session_destruction_failed", name=name, error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to destroy external session {name!r}: {e}",
        )

    msg = (
        f"External session {name!r} already gone"
        if result.get("already_gone")
        else f"External session {name!r} destroyed"
    )
    return SuccessResponse(message=msg)
