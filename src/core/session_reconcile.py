
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

import structlog

from src.core.db_models import SESSION_LIFECYCLE_RUNNING, SESSION_LIFECYCLE_STOPPED

logger = structlog.get_logger()

RECORD_REFUSED_EPOCH_COLLISION = "refused_epoch_collision"

RECORD_REFUSED_INSTANCE_MISMATCH = "refused_instance_mismatch"

RECORD_REFUSALS = (
    RECORD_REFUSED_EPOCH_COLLISION,
    RECORD_REFUSED_INSTANCE_MISMATCH,
)

RECORD_MERGED = "merged"


def reconcile_existing(
    conn: sqlite3.Connection,
    *,
    existing: Dict[str, Any],
    socket: str,
    name: str,
    epoch: int,
    incoming_origin: str,
    lifecycle: str,
    lifecycle_source: Optional[str],
    incoming_session_id: Optional[str],
    stamp: str,
) -> RecordResult:
    from src.core.session_identity import RecordResult

    stored_session_id = existing.get("tmux_session_id")
    if (
        incoming_session_id is not None
        and stored_session_id is not None
        and str(stored_session_id) != str(incoming_session_id)
    ):
        detail = (
            f"stored session id={existing.get('id')} "
            f"uuid={existing.get('session_uuid')} "
            f"origin={existing.get('origin')} "
            f"adopted_at={existing.get('adopted_at')} "
            f"tmux_session_id={stored_session_id} holds instance "
            f"({socket}, {name}, {epoch}); incoming live instance has "
            f"tmux_session_id={incoming_session_id} origin={incoming_origin} "
            f"lifecycle={lifecycle}. Different tmux sessions, REFUSED, "
            f"nothing written"
        )
        logger.warning(
            "session_instance_id_mismatch_refused",
            tmux_socket=socket,
            tmux_name=name,
            tmux_created_epoch=int(epoch),
            stored_session_id=existing.get("id"),
            stored_session_uuid=existing.get("session_uuid"),
            stored_origin=existing.get("origin"),
            stored_adopted_at=existing.get("adopted_at"),
            stored_lifecycle=existing.get("lifecycle"),
            stored_tmux_session_id=stored_session_id,
            incoming_tmux_session_id=incoming_session_id,
            incoming_origin=incoming_origin,
            incoming_lifecycle=lifecycle,
            note=(
                "tmux #{session_id} is unique per server lifetime, so a "
                "disagreement proves these are two different sessions that "
                "the one-second creation epoch could not separate; merging "
                "would transfer one session's history and ownership badge "
                "to another process"
            ),
            detail=detail,
        )
        return RecordResult(
            outcome=RECORD_REFUSED_INSTANCE_MISMATCH,
            session_id=int(existing["id"]),
            session_uuid=existing.get("session_uuid"),
            detail=detail,
        )

    if existing.get("lifecycle") == SESSION_LIFECYCLE_STOPPED:
        detail = (
            f"stored session id={existing.get('id')} "
            f"uuid={existing.get('session_uuid')} "
            f"origin={existing.get('origin')} "
            f"adopted_at={existing.get('adopted_at')} "
            f"lifecycle=stopped already holds instance "
            f"({socket}, {name}, {epoch}); incoming live instance "
            f"({socket}, {name}, {epoch}) origin={incoming_origin} "
            f"lifecycle={lifecycle} REFUSED, nothing written"
        )
        logger.warning(
            "session_instance_epoch_collision_refused",
            tmux_socket=socket,
            tmux_name=name,
            tmux_created_epoch=int(epoch),
            stored_session_id=existing.get("id"),
            stored_session_uuid=existing.get("session_uuid"),
            stored_origin=existing.get("origin"),
            stored_adopted_at=existing.get("adopted_at"),
            stored_lifecycle=existing.get("lifecycle"),
            incoming_origin=incoming_origin,
            incoming_lifecycle=lifecycle,
            note=(
                "tmux #{session_created} has one-second resolution; a stopped "
                "row cannot be the live instance, so the merge is refused "
                "rather than overwriting another session's history"
            ),
            detail=detail,
        )
        return RecordResult(
            outcome=RECORD_REFUSED_EPOCH_COLLISION,
            session_id=int(existing["id"]),
            session_uuid=existing.get("session_uuid"),
            detail=detail,
        )

    sets = [
        "lifecycle = ?",
        "lifecycle_checked_at = ?",
        "lifecycle_source = ?",
        "updated_at = ?",
    ]
    values: List[Any] = [lifecycle, stamp, lifecycle_source, stamp]
    if lifecycle == SESSION_LIFECYCLE_RUNNING:
        sets.append("last_seen_running_at = ?")
        values.append(stamp)
    if incoming_session_id is not None and stored_session_id is None:
        sets.append("tmux_session_id = ?")
        values.append(str(incoming_session_id))
    values.append(int(existing["id"]))
    conn.execute(
        f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", values
    )
    return RecordResult(
        outcome=RECORD_MERGED,
        session_id=int(existing["id"]),
        session_uuid=existing.get("session_uuid"),
    )


