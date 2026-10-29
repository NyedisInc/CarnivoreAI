
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

from src.core.session_conversations import classify
from src.core.session_conversations import constants as K

logger = structlog.get_logger()


@dataclass(frozen=True)
class PendingFlip:

    session_uuid: Optional[str]
    previous_id: str
    new_id: str
    reason: str
    state_dir: Optional[Path] = None
    db_path: Optional[Path] = None


def save_event_for(ended_reason: str) -> str:
    return K.ENDED_CLEAR if ended_reason in K.CLEAR_FAMILY else ended_reason


def _path_of(conversation_id: str, working_dir: Optional[str], corpus_root: Optional[Path]) -> Optional[Path]:
    from src.core.session_transcript_presence import CONVERSATION_PRESENT, conversation_presence

    found = conversation_presence(conversation_id, working_dir=working_dir, corpus_root=corpus_root)
    return found.path if found.outcome == CONVERSATION_PRESENT else None


def _datastore_file(conn: sqlite3.Connection) -> Optional[Path]:
    try:
        for _seq, name, file in conn.execute("PRAGMA database_list").fetchall():
            if name == "main" and file:
                return Path(file)
    except sqlite3.Error as exc:
        logger.warning("conversation_flip_datastore_unknown", error=str(exc))
    return None


def begin_flip(conn: sqlite3.Connection, *, socket: str, tmux_name: str, epoch: Optional[int], previous_id: str,
               new_id: str, working_dir: Optional[str], corpus_root: Optional[Path] = None,
               state_dir: Optional[Path] = None, db_path: Optional[Path] = None) -> PendingFlip:
    new_path = _path_of(new_id, working_dir, corpus_root)
    head = classify.read_head(new_path) if new_path else classify.Head()
    reason = classify.ended_reason(head, previous_id)
    session_uuid: Optional[str] = None
    try:
        from src.core.session_store import get_instance

        anchor = get_instance(conn, socket=socket, name=tmux_name, epoch=epoch)
        if anchor is not None and anchor.get("claude_session_uuid") == previous_id:
            session_uuid = anchor.get("session_uuid")
    except (sqlite3.Error, OSError, KeyError, TypeError) as exc:
        logger.warning("conversation_flip_prepare_failed", tmux_name=tmux_name, error=str(exc),
                       error_type=type(exc).__name__)
    if db_path is None:
        db_path = _datastore_file(conn)
    if state_dir is None and db_path is not None:
        state_dir = db_path.parent
    return PendingFlip(session_uuid=session_uuid, previous_id=previous_id, new_id=new_id, reason=reason,
                       state_dir=state_dir, db_path=db_path)


def finish_flip(pending: PendingFlip):
    if pending.session_uuid is None:
        logger.info("conversation_flip_unsaved", previous=pending.previous_id, new=pending.new_id,
                    reason="no session row resolved")
        return None
    from src.core.pipeline import triggers

    event = save_event_for(pending.reason)
    logger.info("conversation_flip_save", session_uuid=pending.session_uuid, previous=pending.previous_id,
                new=pending.new_id, ended_reason=pending.reason, save_event=event)
    try:
        return triggers.schedule_for_conversation(pending.previous_id, pending.session_uuid, event,
                                                  child_conversation_id=pending.new_id,
                                                  state_dir=pending.state_dir, db_path=pending.db_path)
    except (RuntimeError, OSError, ValueError, sqlite3.Error) as exc:
        logger.error("conversation_flip_save_failed", previous=pending.previous_id, error=str(exc),
                     error_type=type(exc).__name__)
        return None
