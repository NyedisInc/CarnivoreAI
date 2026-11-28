
from __future__ import annotations

import dataclasses
from contextlib import closing
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api import asleep_themes, asleep_wake_listing
from src.api import recreate_routes as rr
from src.api.asleep_offloaded import stamp_offloaded
from src.api.peer_auth import require_peer_sessions
from src.api.session_record_payload import _session_record_payload, attach_host_labels
from src.core import restart_inflight, session_change_notice, session_sleep
from src.core.pipeline import triggers as save_triggers
from src.core.read_caches.ttl_flight import TtlFlight
from src.core.session_ops import row_probe
from src.core.session_ops import sleep as sleep_ops
from src.models import SessionRecord, SuccessResponse
from src.api.error_response import api_error

logger = structlog.get_logger()

WAKE_NOT_ASLEEP_CODE = "session_not_asleep"

router = APIRouter(tags=["sessions"])


class SleepResponse(BaseModel):
    """What a sleep did, or why it did nothing."""

    status: str = Field(
        ...,
        description=(
            "'asleep' when the agent and its tmux session were stopped and "
            "the row now reads asleep; 'refused' when a gate declined, and "
            "then nothing was stopped"
        ),
    )
    session_uuid: str = Field(..., description="the row that was acted on")
    session_name: Optional[str] = Field(
        None, description="the tmux name the row carries, read off the record"
    )
    code: Optional[str] = Field(
        None, description="on 'refused', which gate declined (a REFUSED_* word)"
    )
    detail: str = Field("", description="one sentence, fit to show verbatim")


def sleep_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, restart_inflight.RestartInFlightError):
        return api_error(409, restart_inflight.IN_PROGRESS_CODE, exc)
    if isinstance(exc, row_probe.RowDatastoreUnreadable):
        return api_error(503, "datastore_unavailable", exc)
    if isinstance(exc, row_probe.RowNotFound):
        return api_error(404, "session_not_found", exc)
    if isinstance(exc, row_probe.RowOnRemoteHost):
        return api_error(409, "remote_host", exc)
    if isinstance(exc, row_probe.RowNeverHadTmux):
        return api_error(409, "session_has_no_tmux", exc)
    if isinstance(exc, row_probe.UnsafeTmuxName):
        return api_error(400, "session_name_invalid", exc, name=exc.name)
    if isinstance(exc, sleep_ops.SleepFailed):
        return api_error(500, "session_sleep_failed", exc, tmux_name=exc.tmux_name)
    return api_error(500, "internal_error", exc)


async def sleep_by_uuid(
    app_state: Any,
    session_uuid: str,
    *,
    source: str = session_sleep.LIFECYCLE_SOURCE_SLEPT,
    fresh_ok: bool = False,
) -> SleepResponse:
    try:
        outcome = await sleep_ops.sleep_session(app_state, session_uuid, source=source, fresh_ok=fresh_ok)
    except sleep_ops.SLEEP_ERRORS as exc:
        raise sleep_error_to_http(exc) from exc
    return SleepResponse(**dataclasses.asdict(outcome))


@router.post(
    "/sessions/{session_uuid}/sleep",
    response_model=SleepResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def sleep_session(request: Request, session_uuid: str) -> SleepResponse:
    """Stop this session's agent and close its tmux session; keep the row, asleep.

    Description: the HTTP face of ``session_ops.sleep.sleep_session``, which holds every gate and the close.
    Raises: HTTPException - 400, 404, 409, 500, 503 as :func:`sleep_error_to_http` maps the typed errors.
    """
    return await sleep_by_uuid(request.app.state, session_uuid)


class WakeRequest(BaseModel):
    """An optional explicit wrapper for a wake (issue #714)."""

    agent_type: Optional[str] = Field(
        None,
        description=(
            "a configured wrapper id the user picked. Omitted, the wake uses "
            "the row's own recorded wrapper, or answers 'wrapper_needed'"
        ),
    )
    account_id: Optional[str] = Field(
        None,
        description=(
            "claude account to wake on (GET /sessions/{session_uuid}/restart/accounts); "
            "omit to use the session's pinned account, else the active one"
        ),
    )
    account_pinned: bool = Field(
        False,
        description="With account_id: true saves it for this session, false clears any saved account",
    )
    start_fresh: bool = Field(
        False,
        description=(
            "start a NEW conversation on this row (same name, pin and group) when, and only when, the stored "
            "conversation has no transcript in any login's folder (a wake refused 'transcript_missing'). If a "
            "transcript exists the wake resumes it as usual; nothing is ever discarded"
        ),
    )


class WakeResponse(rr.RecreateResponse):

    code: Optional[str] = Field(
        None,
        description=(
            "on 'refused', 'wrapper_needed' when the row has no wrapper a wake "
            "may launch unasked: open the wrapper picker and wake again with "
            "the pick as agent_type; 'transcript_missing' when no login's folder holds the "
            "conversation: offer to wake again with start_fresh"
        ),
    )
    codes: List[str] = Field(
        default_factory=list,
        description=(
            "every wire code for the refusal: 'wrapper_needed' (old clients and peers read it) and "
            "'launch_profile_needed' (new clients), both for the same case (issue #1257)"
        ),
    )
    wrapper_options: List[str] = Field(
        default_factory=list,
        description="the configured wrapper ids, on 'wrapper_needed'",
    )


def _wrapper_needed(row: dict, ids: Optional[List[str]]) -> WakeResponse:
    from src.core import session_wake_choice as wc

    options = list(ids or [])
    logger.info("session_wake_wrapper_needed", session_uuid=row.get("session_uuid"),
                recorded=row.get("agent_type"), source=row.get("agent_family_source"))
    return WakeResponse(
        status="refused",
        session_uuid=str(row.get("session_uuid")),
        session_name=row.get("tmux_name"),
        presence="unknown",
        conversation="unknown",
        detail=wc.wrapper_needed_detail(row, options),
        code=wc.WAKE_WRAPPER_NEEDED,
        codes=[wc.WAKE_WRAPPER_NEEDED, "launch_profile_needed"],
        wrapper_options=options,
    )


def _carry_crosstalk_grants(session_uuid: str, old_epoch: Any) -> None:
    from src.core.crosstalk import store as crosstalk_store

    try:
        fresh = rr._resolved(row_probe.read_row(session_uuid), session_uuid)
        crosstalk_store.carry_contact_epochs(session_uuid, old_epoch, fresh.get("tmux_created_epoch"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("wake_crosstalk_carry_failed", session_uuid=session_uuid, error=str(exc))


async def wake_by_uuid(
    app_state: Any, session_uuid: str, agent_type: Optional[str] = None, *,
    account_id: Optional[str] = None, account_pinned: bool = False, extra_env: Optional[Dict[str, str]] = None,
    fork: bool = False, fresh: bool = False, start_fresh: bool = False,
) -> WakeResponse:
    from src.api.recreate_action import recreate_by_uuid
    from src.api.session_wake_in_place import wake_dead_pane
    from src.config import settings
    from src.core.session_agent_choice import configured_wrapper_ids
    from src.core.session_wake_choice import recorded_wake_agent

    from src.api.swarm_switch_routes import refuse_held_body
    from src.core.swarm import plain_wake

    await refuse_held_body(session_uuid)
    picked = (agent_type or "").strip()
    try:
        with restart_inflight.claim(session_uuid):
            row = rr._resolved(await run_in_threadpool(row_probe.read_row, session_uuid), session_uuid)
            if not session_sleep.is_asleep(row):
                raise api_error(409, WAKE_NOT_ASLEEP_CODE, None, session_uuid=session_uuid)
            old_epoch = (row or {}).get("tmux_created_epoch")
            if session_sleep.is_dead_pane_stop(row) and not (fork or fresh or start_fresh or extra_env):
                presence = await run_in_threadpool(
                    row_probe.measure_row_presence, row, rr._safe(str(row.get("tmux_name") or "")),
                    str(row.get("tmux_socket") or row_probe.socket_name()))
                in_place = await wake_dead_pane(app_state, row, presence, agent_type=picked or None,
                                                account_id=account_id, account_pinned=account_pinned)
                if in_place is not None:
                    logger.info("session_wake", session_uuid=session_uuid, status=in_place.status,
                                agent_type=picked or None, picked=bool(picked), in_place=True)
                    if in_place.status == "started":
                        await plain_wake.adopt(app_state, session_uuid, in_place.session_id, False)
                        session_change_notice.publish(
                            app_state, session_change_notice.build_structural_notice("woken"))
                    return in_place
            agent_type = picked
            if not agent_type:
                ids = await run_in_threadpool(configured_wrapper_ids, settings)
                agent_type = recorded_wake_agent(row, ids) or ""
                if not agent_type:
                    return _wrapper_needed(row, ids)
            result = await recreate_by_uuid(
                session_uuid,
                agent_type,
                get_manager=lambda: app_state.session_manager,
                **({"account_id": account_id, "account_pinned": account_pinned} if account_id else {}),
                **({"extra_env": extra_env} if extra_env else {}),
                **({"fork": True} if fork else {}),
                **({"fresh": True} if fresh else {}),
                **({"fresh_if_transcript_absent": True} if start_fresh else {}),
            )
    except restart_inflight.RestartInFlightError as exc:
        raise api_error(409, restart_inflight.IN_PROGRESS_CODE, exc) from exc
    if result.status == "started":
        await run_in_threadpool(_carry_crosstalk_grants, session_uuid, old_epoch)
        await plain_wake.adopt(app_state, session_uuid, result.session_id, bool(fresh or start_fresh))
        session_change_notice.publish(
            app_state, session_change_notice.build_structural_notice("woken")
        )
    logger.info("session_wake", session_uuid=session_uuid, status=result.status,
                agent_type=agent_type, picked=bool(picked))
    return WakeResponse(**result.model_dump())


@router.post(
    "/sessions/{session_uuid}/wake",
    response_model=WakeResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def wake_session(
    request: Request, session_uuid: str, body: Optional[WakeRequest] = Body(None)
) -> WakeResponse:
    """Bring an asleep session back, resumed into the same conversation.

    Description: the HTTP face of :func:`wake_by_uuid`, which holds every gate.
    Raises: HTTPException - as :func:`wake_by_uuid` does.
    """
    if body and (body.account_id or body.account_pinned) and getattr(request.state, "peer_grant", None) is not None:
        raise HTTPException(status_code=400, detail="an account is chosen on the computer that runs the session")
    if body and body.account_pinned and not body.account_id:
        raise HTTPException(status_code=400, detail="account_pinned needs an account_id")
    return await wake_by_uuid(
        request.app.state, session_uuid, body.agent_type if body else None,
        account_id=body.account_id if body else None, account_pinned=body.account_pinned if body else False,
        start_fresh=bool(body and body.start_fresh))


@router.delete(
    "/sessions/{session_uuid}/asleep",
    response_model=SuccessResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def kill_asleep_session(request: Request, session_uuid: str, confirm_name: Optional[str] = None) -> SuccessResponse:
    """Kill an ASLEEP agent: take its record off every list, for good.

    Description: an asleep session has no tmux pane, so there is nothing to
      stop. This is the same soft delete ``DELETE /sessions/records/{uuid}``
      runs (``archived_at`` stamped, row kept), behind the asleep gate: a
      row that is not asleep NOW (it woke, or never slept) is refused 409
      and no live pane is ever touched. Runs under the same one-per-row
      claim a wake takes, so a wake and a kill of one row never interleave.
      The conversation transcript and the ``cloude.db`` archive are NOT
      touched. The drawer drops the row through the structural notice.
    Inputs: request (Request). session_uuid (str, path). confirm_name (str,
      query) - a Swarm leader's exact display name, required for its row.
    Output: SuccessResponse.
    Raises: HTTPException 404 (no such row), 409 (not asleep, or a wake or
      restart of this row in flight, or ``leader_protected``), 503 (datastore unreadable).
    Example: DELETE /api/v1/sessions/<uuid>/asleep
    """
    from src.core import session_store
    from src.core.db import DatastoreUnreadableError, connect
    from src.core.swarm import leaders as swarm_leaders

    await swarm_leaders.require_confirm(session_uuid=session_uuid, confirm_name=confirm_name)

    def _kill() -> bool:
        with closing(connect(row_probe.db_path(), create=False)) as conn:
            found = conn.execute(
                "SELECT * FROM sessions WHERE session_uuid = ?", (session_uuid,)
            ).fetchone()
            if found is None:
                raise HTTPException(status_code=404, detail=f"no session record {session_uuid}")
            if not session_sleep.is_asleep(dict(found)):
                raise HTTPException(
                    status_code=409,
                    detail="this session is not asleep, so it is not killed from here",
                )
            return session_store.archive_session(conn, session_uuid)

    try:
        with restart_inflight.claim(session_uuid):
            performed = await run_in_threadpool(_kill)
    except restart_inflight.RestartInFlightError as exc:
        raise api_error(409, restart_inflight.IN_PROGRESS_CODE, exc) from exc
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step="_kill") from exc
    if performed:
        save_triggers.schedule_for_uuid(session_uuid, save_triggers.EVENT_REMOVE)
        session_change_notice.publish(
            request.app.state, session_change_notice.build_structural_notice("destroyed")
        )
    logger.info("session_kill_asleep", session_uuid=session_uuid, performed=performed)
    return SuccessResponse(message="Asleep session killed (the conversation is kept)")


@router.get(
    "/sessions/asleep",
    response_model=List[SessionRecord],
    dependencies=[Depends(require_peer_sessions)],
)
async def list_asleep_sessions(request: Request, include_swarm: bool = False) -> Any:
    """Every asleep session, newest first. A paired computer gets only the rows this one owns, slim (``peer_serve.serve_asleep_to_peer``).

    Description: read from the stored rows; an asleep session has no tmux
      session for a live listing to find. Empty when the datastore does not
      exist yet. Peer callers may pass ``include_swarm=true`` for read-only
      Swarm asleep summaries (#3385).
    Inputs: request (Request); include_swarm (bool).
    Output: list[SessionRecord] or JSONResponse of slim peer rows.
    Raises: HTTPException 503 - the datastore exists but is unreadable.
    """
    grant = getattr(request.state, "peer_grant", None)
    if grant is not None:
        caller_iid = getattr(grant, "peer_install_id", None)
        return JSONResponse(await _peer_asleep_rows(include_swarm=include_swarm, caller_install_id=caller_iid))
    return await asleep_record_rows(request.app.state)


async def _peer_asleep_rows(
    *,
    include_swarm: bool = False,
    caller_install_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    from src.api import peer_auth
    from src.core.federation import peer_serve

    if include_swarm or caller_install_id is not None:
        return list(
            await run_in_threadpool(
                peer_serve.serve_asleep_to_peer,
                peer_auth.open_db,
                include_swarm=include_swarm,
                caller_install_id=caller_install_id,
            )
        )
    return list(await PEER_ASLEEP_CACHE.get(lambda: run_in_threadpool(peer_serve.serve_asleep_to_peer, peer_auth.open_db)))


@router.get("/sessions/list-and-asleep", dependencies=[Depends(require_peer_sessions)])
async def list_and_asleep(
    request: Request,
    include_swarm: bool = False,
    include_relayed: bool = True,
) -> JSONResponse:
    """``/sessions/list`` and ``/sessions/asleep`` in ONE call: ``{"list": [...], "asleep": [...]}`` (issue #2632).

    Description: each half is exactly what its own route answers THIS caller (the owner's rows plus the paired computers', or a paired
      computer's own-rows-only slim copy), so a client that read both gets the same data for one request. For peer callers,
      ``relayed`` carries additive 1-hop read-only summaries of other connected non-one-way peers (#3385) while keeping ``list``
      strictly 1-hop owned rows for loop guard F8. The two old routes stay.
    Inputs: request (Request); include_swarm (bool); include_relayed (bool).
    Output: JSONResponse.
    Example: GET /api/v1/sessions/list-and-asleep -> {"list": [SessionInfo...], "asleep": [SessionRecord...]}
    """
    import asyncio
    from src.api import peer_auth
    from src.api.session_crud_routes import list_sessions
    from src.core.federation import peer_listing

    grant = getattr(request.state, "peer_grant", None)
    is_peer = grant is not None
    caller_iid = getattr(grant, "peer_install_id", None)
    asleep_coro = (
        _peer_asleep_rows(include_swarm=include_swarm, caller_install_id=caller_iid)
        if is_peer
        else asleep_record_rows(request.app.state)
    )
    infos, asleep_raw = await asyncio.gather(
        list_sessions(request, include_swarm=include_swarm, include_relayed=False),
        asleep_coro,
    )
    relayed_infos: Optional[List[Any]] = None
    if is_peer and include_relayed:
        relayed_infos = await asyncio.to_thread(
            peer_listing.relayed_for_peer,
            peer_auth.open_db,
            None,
            caller_install_id=caller_iid,
            include_swarm=include_swarm,
        )

    def _serialize() -> Dict[str, Any]:
        asleep_out = asleep_raw if is_peer else [r.model_dump(mode="json") for r in asleep_raw]
        payload: Dict[str, Any] = {"list": [i.model_dump(mode="json") for i in infos], "asleep": asleep_out}
        if relayed_infos is not None:
            payload["relayed"] = [i.model_dump(mode="json") for i in relayed_infos]
        return payload

    return JSONResponse(await asyncio.to_thread(_serialize))


PEER_ASLEEP_CACHE: TtlFlight = TtlFlight("peer_asleep_rows", 1.0)


ASLEEP_CACHE: TtlFlight = TtlFlight("asleep_rows", 1.0)


async def asleep_record_rows(app_state: Any, infos: Optional[List[Any]] = None,
                             wake_shared: Optional[Dict[str, Any]] = None) -> List[SessionRecord]:
    return list(await ASLEEP_CACHE.get(lambda: _assemble_asleep_rows(app_state, infos, wake_shared)))


async def _assemble_asleep_rows(app_state: Any, infos: Optional[List[Any]] = None,
                                wake_shared: Optional[Dict[str, Any]] = None) -> List[SessionRecord]:
    from src.core.db import DatastoreUnreadableError
    from src.core.db_reuse.core_read import lend_pooled_read

    db_path = row_probe.db_path()
    if not db_path.exists():
        return []

    def _read() -> tuple:
        conn = lend_pooled_read(db_path)
        if conn is None:
            raise DatastoreUnreadableError(f"{db_path.name} cannot be opened at {db_path}", db_path)
        try:
            found = session_sleep.asleep_rows(conn)
            attach_host_labels(conn, found)
        finally:
            conn.close()
        return found, asleep_themes.read_dotfile_themes(found)

    try:
        rows, dotfile_themes = await run_in_threadpool(_read)
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc, step="_read") from exc
    manager = getattr(app_state, "session_manager", None)
    store = getattr(manager, "_unread_store", None)
    themes = getattr(manager, "_theme_store", None)
    if themes is not None:
        themes = asleep_themes.PrefetchedThemes(themes, dotfile_themes)
    def project() -> List[SessionRecord]:
        projected = [_session_record_payload(row, store, themes) for row in rows]
        stamp_offloaded(rows, projected)
        return projected

    records = await run_in_threadpool(project)
    await asleep_wake_listing.stamp_next_wake(app_state, records, infos, wake_shared)
    from src.api.swarm_member_listing import mark_swarm_members

    await mark_swarm_members(records, row_attr="id")
    return records
