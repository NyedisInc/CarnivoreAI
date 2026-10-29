
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Optional

import structlog

from src.core.db_models import (
    SESSION_FAMILY_SOURCE_LAUNCHED,
    SESSION_FAMILY_SOURCE_NOT_LAUNCHED,
    SESSION_LIFECYCLE_RUNNING,
    SESSION_ORIGIN_CREATED,
)
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.launch_record import record_launch_on_row, write_launch_record
from src.core.session_adopt_persist import find_live_instance
from src.core.session_project_binding import resolve_project_binding
from src.core.tmux_listing import TmuxListing

logger = structlog.get_logger()

CREATE_LIFECYCLE_SOURCE = "create"

CREATE_RECORDED = "recorded"

CREATE_LISTING_UNAVAILABLE = "listing_unavailable"

CREATE_SESSION_GONE = "session_gone"

CREATE_REFUSED = "refused"

CREATE_NO_DATASTORE = "no_datastore"

CREATE_NOT_TMUX_BACKED = "not_tmux_backed"


@dataclass(frozen=True)
class CreatePersistResult:

    outcome: str
    session_uuid: Optional[str] = None
    epoch: Optional[int] = None
    detail: Optional[str] = None

    @property
    def recorded(self) -> bool:
        return self.outcome == CREATE_RECORDED


def persist_creation(
    conn: sqlite3.Connection,
    *,
    socket: str,
    name: str,
    listing: TmuxListing,
    working_dir: Optional[str] = None,
    working_dir_probe: Optional[Callable[[str], Optional[str]]] = None,
    agent_type: Optional[str] = None,
    agent_family: Optional[str] = None,
    agent_launched: Optional[bool] = None,
    reuse_session_id: Optional[int] = None,
    label: Optional[str] = None,
    model: Optional[str] = None,
    launch_record: Optional[str] = None,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
    project_name: Optional[str] = None,
) -> CreatePersistResult:
    from src.core.session_identity import record_instance

    if not listing.ok:
        logger.warning(
            "create_persist_listing_unavailable",
            tmux_name=name,
            listing_reason=listing.reason,
            note=(
                "the session was created but tmux could not be listed, so "
                "its creation epoch is unknown and no row can be keyed. "
                "The session is live and unattributed, which a later "
                "create-path retry or an adopt repairs"
            ),
        )
        return CreatePersistResult(
            outcome=CREATE_LISTING_UNAVAILABLE,
            detail=(
                "could not ask tmux for the new session's creation time "
                f"({listing.reason or 'probe_error'})"
            ),
        )

    live = find_live_instance(listing, name)
    if live is None:
        logger.warning(
            "create_persist_session_gone",
            tmux_name=name,
            tmux_socket=socket,
            note=(
                "the listing RAN and does not contain the name we just "
                "created, so the session died immediately. Nothing is "
                "recorded: a row here would claim a session that is not "
                "there"
            ),
        )
        return CreatePersistResult(
            outcome=CREATE_SESSION_GONE,
            detail="the new session was gone by the time tmux was listed",
        )

    try:
        epoch = int(live.get("created_at_epoch"))
    except (TypeError, ValueError):
        logger.warning(
            "create_persist_epoch_unreadable",
            tmux_name=name,
            raw_epoch=live.get("created_at_epoch"),
        )
        return CreatePersistResult(
            outcome=CREATE_LISTING_UNAVAILABLE,
            detail="the new session reported no usable creation time",
        )

    resolved_dir = working_dir or live.get("working_dir")
    if resolved_dir is None and working_dir_probe is not None:
        resolved_dir = working_dir_probe(name)
    if host_key != LOCAL_HOST_KEY:
        from src.core.hosts.remote_project import bind_remote_project

        binding = bind_remote_project(conn, host_key, str(resolved_dir), now=now)
    else:
        binding = resolve_project_binding(
            conn, resolved_dir, allow_create=True, now=now, display_name=project_name
        )
    project_id, attribution = binding.project_id, binding.attribution

    resolved_title = label if label else None

    if agent_launched is True:
        recorded_agent_type = agent_type
        recorded_agent_family = agent_family
        family_source = SESSION_FAMILY_SOURCE_LAUNCHED
    elif agent_launched is False:
        recorded_agent_type = None
        recorded_agent_family = None
        family_source = SESSION_FAMILY_SOURCE_NOT_LAUNCHED
    else:
        recorded_agent_type = None
        recorded_agent_family = None
        family_source = None

    if reuse_session_id is not None:
        from src.core.session_restart import rebind_instance

        rebound = rebind_instance(
            conn,
            row_id=int(reuse_session_id),
            socket=socket,
            name=name,
            epoch=epoch,
            tmux_session_id=live.get("tmux_session_id"),
            working_dir=resolved_dir,
            lifecycle_source=CREATE_LIFECYCLE_SOURCE,
            now=now,
            host_key=host_key,
        )
        if rebound.rebound:
            record_launch_on_row(
                conn,
                row_id=int(reuse_session_id),
                agent_type=recorded_agent_type,
                agent_family=recorded_agent_family,
                family_source=family_source,
            )
            write_launch_record(conn, session_uuid=rebound.session_uuid, record=launch_record)
            logger.info(
                "create_persisted_by_reuse",
                tmux_name=name,
                tmux_socket=socket,
                tmux_created_epoch=epoch,
                session_uuid=rebound.session_uuid,
                reused_session_id=int(reuse_session_id),
                note=(
                    "restart reused the existing row; no second row was "
                    "inserted, so nothing references a session the user "
                    "cannot see"
                ),
            )
            return CreatePersistResult(
                outcome=CREATE_RECORDED,
                session_uuid=rebound.session_uuid,
                epoch=epoch,
            )
        logger.warning(
            "create_persist_reuse_declined",
            tmux_name=name,
            tmux_socket=socket,
            tmux_created_epoch=epoch,
            reused_session_id=int(reuse_session_id),
            outcome=rebound.outcome,
            detail=rebound.detail,
            note=(
                "falling through to an ordinary instance record; the "
                "session is live and simply keeps a separate row"
            ),
        )

    result = record_instance(
        conn,
        socket=socket,
        name=name,
        epoch=epoch,
        origin=SESSION_ORIGIN_CREATED,
        lifecycle=SESSION_LIFECYCLE_RUNNING,
        lifecycle_source=CREATE_LIFECYCLE_SOURCE,
        session_id=live.get("tmux_session_id"),
        now=now,
        working_dir=resolved_dir,
        project_id=project_id,
        project_attribution=attribution,
        agent_type=recorded_agent_type,
        agent_family=recorded_agent_family,
        agent_family_source=family_source,
        title=resolved_title,
        model=(model or "").strip() or None,
        host_key=host_key,
    )
    if result.refused:
        logger.warning(
            "create_persist_refused",
            tmux_name=name,
            tmux_socket=socket,
            tmux_created_epoch=epoch,
            outcome=result.outcome,
            detail=result.detail,
            note=(
                "a stored row under this triple provably describes a "
                "different session. Nothing written - the new session is "
                "live and unattributed rather than wearing another "
                "session's history"
            ),
        )
        return CreatePersistResult(
            outcome=CREATE_REFUSED,
            epoch=epoch,
            detail=result.detail or "that tmux name refers to a different session",
        )

    write_launch_record(conn, session_uuid=result.session_uuid, record=launch_record)
    logger.info(
        "create_persisted",
        tmux_name=name,
        tmux_socket=socket,
        tmux_created_epoch=epoch,
        session_uuid=result.session_uuid,
        record_outcome=result.outcome,
        project_id=project_id,
        project_binding_rule=binding.rule,
        note=(
            "origin='created' is written once; a MERGE here leaves an "
            "existing origin alone, so this can never demote an adoption"
        ),
    )
    return CreatePersistResult(
        outcome=CREATE_RECORDED,
        session_uuid=result.session_uuid,
        epoch=epoch,
    )
