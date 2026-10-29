
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api import asleep_themes, asleep_wake_listing
from src.api import recreate_routes as rr
from src.api.auth import require_auth
from src.api.peer_auth import require_peer_sessions
from src.api.session_record_payload import _session_record_payload
from src.core import restart_inflight, session_change_notice, session_sleep, unread_follow_up
from src.core.pipeline import triggers as save_triggers
from src.core.session_recreate_presence import TMUX_GONE, TMUX_PRESENT, TMUX_UNKNOWN
from src.models import SessionRecord, SuccessResponse

logger = structlog.get_logger()

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


def _refused(row: dict, refusal: session_sleep.SleepRefusal) -> SleepResponse:
    logger.info(
        "session_sleep_refused",
        session_uuid=row.get("session_uuid"),
        tmux_name=row.get("tmux_name"),
        code=refusal.code,
    )
    return SleepResponse(
        status="refused",
        session_uuid=str(row.get("session_uuid")),
        session_name=row.get("tmux_name"),
        code=refusal.code,
        detail=refusal.detail,
    )


def _record_sleep(row: dict, source: str) -> int:
    from src.core.db import connect

    with closing(connect(rr._db_path(), create=False)) as conn:
        moved = session_sleep.mark_asleep(
            conn,
            row_id=int(row["id"]),
            tmux_name=str(row["tmux_name"]),
            tmux_created_epoch=int(row["tmux_created_epoch"]),
            source=source,
        )
        conn.commit()
        return moved


async def sleep_by_uuid(
    app_state: Any,
    session_uuid: str,
    *,
    source: str = session_sleep.LIFECYCLE_SOURCE_SLEPT,
    fresh_ok: bool = False,
) -> SleepResponse:
    """Stop this session's agent and close its tmux session; keep the row, asleep.

    Description: reads the row by its durable key, runs the gates (not
      deleted, has a tmux identity, running, conversation id known), then
      MEASURES presence on the row's own socket. ``unknown`` refuses: not
      having looked is not a licence to kill. ``present`` closes the
      session (``session_sleep.close_for_sleep``); ``gone`` has nothing to
      close. Then the asleep marker is written onto exactly the instance
      that was read, so the row stays in the running lists, greyed, and is
      never offered as a loss. The uploads bucket and the pinned theme are
      kept, unlike a kill, because the session is coming back to them.
      THE ONE SLEEP. The route below and the auto-sleep pass
      (``src/core/auto_sleep/sleeper.py``, issue #559) both call this, so
      there is no second teardown path.
    Inputs: app_state - ``app.state`` (session manager, local servers, the
      events hub). session_uuid (str). source (str) - the marker written,
      ``slept_by_user`` for the route, ``slept_by_timer`` for the auto-sleep
      pass (:func:`auto_sleep_by_uuid`, issue #715). fresh_ok (bool) - a Swarm
      sleep: skip the conversation gate (``session_sleep.sleep_refusal``).
    Output: SleepResponse.
    Raises: HTTPException 400 (unsafe tmux name), 404 (no such row), 409
      (a restart, recreate or wake of this row is in flight, or the row
      never had a tmux session), 503 (datastore unreadable), 500 (tmux
      refused the kill).
    """
    try:
        with restart_inflight.claim(session_uuid):
            row = rr._resolved(await run_in_threadpool(rr._read_row, session_uuid), session_uuid)
            refusal = session_sleep.sleep_refusal(row, fresh_ok=fresh_ok)
            if refusal is not None:
                return _refused(row, refusal)
            name = rr._safe(str(row.get("tmux_name") or ""))
            socket = str(row.get("tmux_socket") or rr._socket_name())
            presence = await run_in_threadpool(rr._measure_presence, name, socket)
            if presence.outcome == TMUX_UNKNOWN:
                return _refused(row, session_sleep.SleepRefusal(
                    session_sleep.REFUSED_PRESENCE_UNKNOWN,
                    "cannot sleep: the tmux socket could not be listed, so "
                    "whether this session is running was not evaluated. "
                    "nothing was stopped",
                ))
            unread_follow_up.carry_into_sleep(app_state.session_manager, row)
            if presence.outcome == TMUX_PRESENT:
                await app_state.local_servers.clear_session(name)
                try:
                    await session_sleep.close_for_sleep(
                        app_state.session_manager, name=name, socket=socket
                    )
                except RuntimeError as exc:
                    logger.error("session_sleep_close_failed", tmux_name=name, error=str(exc))
                    raise HTTPException(
                        status_code=500,
                        detail=f"failed to close {name!r} for sleep: {exc}",
                    )
                after = await run_in_threadpool(rr._measure_presence, name, socket)
                if after.outcome != TMUX_GONE:
                    logger.error("session_sleep_still_present", tmux_name=name,
                                 presence=after.outcome)
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            f"{name!r} was asked to close but the socket still "
                            f"reads {after.outcome}, so it was not marked asleep"
                        ),
                    )
            moved = await run_in_threadpool(_record_sleep, row, source)
    except restart_inflight.RestartInFlightError as exc:
        raise HTTPException(status_code=409, detail=restart_inflight.http_detail(exc))

    session_change_notice.publish(
        app_state, session_change_notice.build_structural_notice("slept")
    )
    if moved:
        save_triggers.schedule_for_uuid(session_uuid, save_triggers.EVENT_SLEEP)
    if not moved:
        return _refused(row, session_sleep.SleepRefusal(
            session_sleep.REFUSED_ROW_MOVED,
            "the session was closed, but its record changed while it was "
            "being put to sleep, so it was not marked asleep",
        ))
    logger.info("session_slept", session_uuid=session_uuid, tmux_name=name,
                presence=presence.outcome)
    return SleepResponse(
        status="asleep",
        session_uuid=session_uuid,
        session_name=name,
        detail="asleep. wake it from the session menu to resume the same conversation",
    )


async def auto_sleep_by_uuid(app_state: Any, session_uuid: str) -> SleepResponse:
    return await sleep_by_uuid(
        app_state, session_uuid, source=session_sleep.LIFECYCLE_SOURCE_SLEPT_BY_TIMER
    )


@router.post(
    "/sessions/{session_uuid}/sleep",
    response_model=SleepResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def sleep_session(request: Request, session_uuid: str) -> SleepResponse:
    """Stop this session's agent and close its tmux session; keep the row, asleep.

    Description: the HTTP face of :func:`sleep_by_uuid`, which holds every
      gate and the close.
    Raises: HTTPException - as :func:`sleep_by_uuid` does.
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
        fresh = rr._resolved(rr._read_row(session_uuid), session_uuid)
        crosstalk_store.carry_contact_epochs(session_uuid, old_epoch, fresh.get("tmux_created_epoch"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("wake_crosstalk_carry_failed", session_uuid=session_uuid, error=str(exc))


async def wake_by_uuid(
    app_state: Any, session_uuid: str, agent_type: Optional[str] = None, *,
    account_id: Optional[str] = None, account_pinned: bool = False, extra_env: Optional[Dict[str, str]] = None,
    fork: bool = False, fresh: bool = False, start_fresh: bool = False,
) -> WakeResponse:
    """Bring an asleep session back, resumed into the same conversation.

    Description: THE ONE WAKE, called by the route below and by the crosstalk
      bus when an agent addresses an asleep session (docs/crosstalk.md).
      Refuses a row that is not asleep (a live session has nothing to wake,
      and a closed one belongs to Recent's restart), then runs
      ``recreate_by_uuid`` under a wrapper and the same one-per-row claim
      ``POST /sessions/recreate`` takes. THE WRAPPER is ``agent_type`` when the
      user picked one (validated by the recreate's own gate), else the row's
      recorded wrapper when it is a configured one and not an inference
      (``session_wake_choice``). With neither, nothing is launched and the
      answer is ``refused`` with ``code 'wrapper_needed'`` and the configured
      ids, which the client turns into the wrapper picker (issue #714). Every
      gate of the recreate path applies unchanged; a refusal there is a
      ``status='refused'`` answer and the row stays asleep. A DEAD-PANE STOP
      (``session_sleep.is_dead_pane_stop``, #1726) whose husk is still on the
      socket is woken IN PLACE instead (``session_wake_in_place``: the row's own
      dead husk only, ``respawn_session`` with no kill); its husk measured gone
      recreates as any asleep row does.
    Inputs: app_state (``app.state``); session_uuid (str); agent_type (str | None); account_id / extra_env - the
      account and trusted pane variables a MOVED session launches with (``pack/move/account.py``), None for a normal wake;
      account_pinned (bool) - the picker's box with ``account_id`` (``recreate_by_uuid`` applies it); fork / fresh (bool) - a COPY sent
      from another computer resumes as a fork, a FRESH one starts with no conversation (``recreate_by_uuid``). start_fresh (bool) - the
      user's "start fresh" after a ``transcript_missing`` refusal: a new conversation ONLY on a measured absence (``fresh_if_transcript_absent``).
    Output: WakeResponse.
    Raises: HTTPException 404, 409 (not asleep, or a restart of this row
      in flight; ``swarm_off`` for a Swarm agent's body while the global
      Swarm switch is off, docs/swarm.md 4.10), 400, 503, 500 as recreate does.
    """
    from src.api.recreate_action import recreate_by_uuid
    from src.api.session_wake_in_place import wake_dead_pane
    from src.config import settings
    from src.core.session_agent_choice import configured_wrapper_ids
    from src.core.session_wake_choice import recorded_wake_agent

    from src.api.swarm_switch_routes import refuse_held_body

    await refuse_held_body(session_uuid)
    picked = (agent_type or "").strip()
    try:
        with restart_inflight.claim(session_uuid):
            row = rr._resolved(await run_in_threadpool(rr._read_row, session_uuid), session_uuid)
            if not session_sleep.is_asleep(row):
                raise HTTPException(
                    status_code=409,
                    detail="this session is not asleep, so there is nothing to wake",
                )
            old_epoch = (row or {}).get("tmux_created_epoch")
            if session_sleep.is_dead_pane_stop(row) and not (fork or fresh or start_fresh or extra_env):
                presence = await run_in_threadpool(
                    rr._measure_presence, rr._safe(str(row.get("tmux_name") or "")),
                    str(row.get("tmux_socket") or rr._socket_name()))
                in_place = await wake_dead_pane(app_state, row, presence, agent_type=picked or None,
                                                account_id=account_id, account_pinned=account_pinned)
                if in_place is not None:
                    logger.info("session_wake", session_uuid=session_uuid, status=in_place.status,
                                agent_type=picked or None, picked=bool(picked), in_place=True)
                    if in_place.status == "started":
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
        raise HTTPException(status_code=409, detail=restart_inflight.http_detail(exc))
    if result.status == "started":
        await run_in_threadpool(_carry_crosstalk_grants, session_uuid, old_epoch)
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
        with closing(connect(rr._db_path(), create=False)) as conn:
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
        raise HTTPException(status_code=409, detail=restart_inflight.http_detail(exc))
    except DatastoreUnreadableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
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
    dependencies=[Depends(require_auth)],
)
async def list_asleep_sessions(request: Request) -> List[SessionRecord]:
    """Every asleep session, newest first.

    Description: read from the stored rows; an asleep session has no tmux
      session for a live listing to find. Empty when the datastore does not
      exist yet.
    Raises: HTTPException 503 - the datastore exists but is unreadable.
    """
    return await asleep_record_rows(request.app.state)


async def asleep_record_rows(app_state: Any, infos: Optional[List[Any]] = None,
                             wake_shared: Optional[Dict[str, Any]] = None) -> List[SessionRecord]:
    from src.core.db import DatastoreUnreadableError
    from src.core.db_reuse.core_read import lend_pooled_read

    db_path = rr._db_path()
    if not db_path.exists():
        return []

    def _read() -> tuple:
        conn = lend_pooled_read(db_path)
        if conn is None:
            raise DatastoreUnreadableError(f"{db_path.name} cannot be opened at {db_path}", db_path)
        found = session_sleep.asleep_rows(conn)
        return found, asleep_themes.read_dotfile_themes(found)

    try:
        rows, dotfile_themes = await run_in_threadpool(_read)
    except DatastoreUnreadableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    manager = getattr(app_state, "session_manager", None)
    store = getattr(manager, "_unread_store", None)
    themes = getattr(manager, "_theme_store", None)
    if themes is not None:
        themes = asleep_themes.PrefetchedThemes(themes, dotfile_themes)
    records = [_session_record_payload(row, store, themes) for row in rows]
    await asleep_wake_listing.stamp_next_wake(app_state, records, infos, wake_shared)
    return records
