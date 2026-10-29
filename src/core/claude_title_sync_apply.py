
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import structlog

from src.core.claude_title_sync import (
    TITLE_APPLIED,
    TITLE_BASELINE_RECORDED,
    TITLE_NOT_MEASURED,
    decide_title_application,
    read_newest_custom_title,
    registry_user_title,
)
from src.core.sessions.lazy_write import DatastoreNotWritable, lazy_datastore

logger = structlog.get_logger()

SYNC_NO_SESSION: str = "no_session"

SYNC_NO_CONVERSATION: str = "no_conversation"

SYNC_NO_TRANSCRIPT: str = "no_transcript"

SYNC_UNAVAILABLE: str = "unavailable"

SYNC_RAN: str = "ran"

_TRANSCRIPT_PATHS: Dict[str, str] = {}


@dataclass(frozen=True)
class TitleSyncResult:

    outcome: str
    action: Optional[str] = None
    title: Optional[str] = None
    broadcast_title: Optional[str] = None
    detail: Optional[str] = None
    retry: Optional[Any] = None


def _tmux_name_for(session_manager: Any, session_id: str) -> Optional[str]:
    sess = session_manager._registry.get_session(session_id)
    name = getattr(sess, "tmux_session", None) if sess else None
    if name:
        return str(name)
    authority = getattr(session_manager, "hook_tokens", None)
    name = authority.name_for(session_id) if authority is not None else None
    if name:
        return str(name)
    return session_id or None


def _transcript_path_for(uuid: str, working_dir: Optional[str]) -> Optional[str]:
    cached = _TRANSCRIPT_PATHS.get(uuid)
    if cached:
        return cached

    from src.core.session_transcript_presence import conversation_presence

    presence = conversation_presence(uuid, working_dir=working_dir)
    if presence.path is None:
        return None
    resolved = str(presence.path)
    _TRANSCRIPT_PATHS[uuid] = resolved
    return resolved


def _parse_created_at(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _registry_evidence(
    observed: Optional[str],
    *,
    tmux_name: str,
    uuid: str,
    row_id: int,
    current_title: Optional[str],
    claude_title: Optional[str],
    created_at: Any,
) -> Tuple[Optional[str], bool]:
    recorded = (claude_title or "").strip() or None
    if not observed or observed == (current_title or "").strip():
        return None, False
    if recorded is not None and recorded != observed:
        return None, False

    from src.core.attention.registry_index import registry_for_session

    record = registry_for_session(tmux_name=tmux_name, claude_session_uuid=uuid)
    user_title = registry_user_title(
        record, row_created_at=_parse_created_at(created_at)
    )
    if user_title is None or recorded is None:
        return user_title, False

    from src.core import claude_rename_retry_store as retry_store

    mark = retry_store.mark_for(
        retry_store.resolve_state_dir(), f"{uuid}:{row_id}"
    )
    return user_title, mark is not None and mark.agreed_title == recorded


def sync_claude_title(session_manager: Any, session_id: str) -> TitleSyncResult:
    tmux_name = _tmux_name_for(session_manager, session_id)
    if not tmux_name:
        return TitleSyncResult(
            SYNC_NO_SESSION,
            detail="no tmux name for this session, so no row can be keyed",
        )

    conn = None
    try:
        conn = lazy_datastore(session_manager)
        if conn is None:
            return TitleSyncResult(
                SYNC_UNAVAILABLE,
                detail="the datastore could not be opened for writing",
            )

        from src.core.session_store import identity_for_live_name

        identity = identity_for_live_name(
            conn,
            socket=session_manager.tmux_socket_name(),
            name=tmux_name,
        )
        if not identity:
            return TitleSyncResult(
                SYNC_NO_CONVERSATION,
                detail="no instance row for this tmux name",
            )

        row = conn.execute(
            "SELECT claude_session_uuid, title, claude_title, working_dir, "
            "agent_family, created_at FROM sessions WHERE id = ?",
            (identity["id"],),
        ).fetchone()
        if row is None:
            return TitleSyncResult(
                SYNC_NO_CONVERSATION,
                detail="the identified row disappeared between two reads",
            )

        row_id = identity["id"]
        uuid, current_title, claude_title, working_dir, agent_family = (
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
        )
        created_at = row[5]
        if not uuid:
            return TitleSyncResult(
                SYNC_NO_CONVERSATION,
                detail=(
                    "no claude conversation is bound to this row yet, so "
                    "there is no transcript to read a name out of"
                ),
            )

        path = _transcript_path_for(str(uuid), working_dir)
        if not path:
            return TitleSyncResult(
                SYNC_NO_TRANSCRIPT,
                detail=(
                    "a conversation uuid is recorded but no transcript "
                    "for it is on this machine"
                ),
            )

        read = read_newest_custom_title(path)
        user_title, ordered = _registry_evidence(
            read.title if read.found else None,
            tmux_name=tmux_name,
            uuid=str(uuid),
            row_id=row_id,
            current_title=current_title,
            claude_title=claude_title,
            created_at=created_at,
        )
        verdict = decide_title_application(
            read,
            current_title=current_title,
            recorded_claude_title=claude_title,
            registry_user_title=user_title,
            browser_rename_ordered=ordered,
        )

        def _with_retry(
            result: TitleSyncResult,
            *,
            effective_title: Optional[str],
            effective_claude_title: Optional[str],
        ) -> TitleSyncResult:
            from src.core.claude_rename_retry_apply import run_rename_retry

            return replace(
                result,
                retry=run_rename_retry(
                    session_id=session_id,
                    row_id=row_id,
                    title=effective_title,
                    claude_title=effective_claude_title,
                    claude_uuid=str(uuid),
                    agent_family=agent_family,
                    sync_action=verdict.action,
                ),
            )

        if verdict.action == TITLE_NOT_MEASURED:
            return _with_retry(
                TitleSyncResult(
                    SYNC_RAN, action=verdict.action, detail=verdict.detail
                ),
                effective_title=current_title,
                effective_claude_title=claude_title,
            )

        if verdict.action == TITLE_BASELINE_RECORDED:
            from src.core.db import transaction

            with transaction(conn):
                conn.execute(
                    "UPDATE sessions SET claude_title = ? WHERE id = ?",
                    (verdict.title, row_id),
                )
            logger.info(
                "claude_title_baseline_recorded",
                session_id=session_id,
                row_id=row_id,
                note="visible title untouched; see claude_title_sync docstring",
            )
            return _with_retry(
                TitleSyncResult(
                    SYNC_RAN,
                    action=verdict.action,
                    title=verdict.title,
                    detail=verdict.detail,
                ),
                effective_title=current_title,
                effective_claude_title=verdict.title,
            )

        if verdict.action == TITLE_APPLIED:
            from src.core.db import transaction

            with transaction(conn):
                if verdict.writes_visible_title:
                    conn.execute(
                        "UPDATE sessions SET title = ?, claude_title = ? "
                        "WHERE id = ?",
                        (verdict.title, verdict.title, row_id),
                    )
                else:
                    conn.execute(
                        "UPDATE sessions SET claude_title = ? WHERE id = ?",
                        (verdict.title, row_id),
                    )
            logger.info(
                "claude_title_synced",
                session_id=session_id,
                row_id=row_id,
                moved_visible_title=verdict.writes_visible_title,
            )
            return _with_retry(
                TitleSyncResult(
                    SYNC_RAN,
                    action=verdict.action,
                    title=verdict.title,
                    broadcast_title=(
                        verdict.title if verdict.writes_visible_title else None
                    ),
                    detail=verdict.detail,
                ),
                effective_title=verdict.title,
                effective_claude_title=verdict.title,
            )

        return _with_retry(
            TitleSyncResult(
                SYNC_RAN, action=verdict.action, detail=verdict.detail
            ),
            effective_title=current_title,
            effective_claude_title=claude_title,
        )
    except DatastoreNotWritable:
        return TitleSyncResult(
            SYNC_UNAVAILABLE,
            detail="the datastore could not be opened for writing",
        )
    except sqlite3.Error as exc:
        logger.debug(
            "claude_title_sync_db_failed", session_id=session_id, error=str(exc)
        )
        return TitleSyncResult(
            SYNC_UNAVAILABLE, detail=f"the datastore refused the read: {exc}"
        )
    except OSError as exc:
        logger.debug(
            "claude_title_sync_io_failed", session_id=session_id, error=str(exc)
        )
        return TitleSyncResult(
            SYNC_UNAVAILABLE, detail=f"the transcript could not be reached: {exc}"
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
