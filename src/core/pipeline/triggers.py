
from __future__ import annotations

import sqlite3
import time
from concurrent.futures import Future
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import structlog

logger = structlog.get_logger()

EVENT_KILL: str = "kill"
EVENT_REMOVE: str = "remove"
EVENT_SLEEP: str = "sleep"
EVENT_RESTART: str = "restart"
STATE_DONE: str = "done"
STATE_REFUSED: str = "refused"

ROW_SQL = (
    "SELECT s.session_uuid, s.claude_session_uuid, s.agent_family, s.agent_type, "
    "s.working_dir, s.host_key, s.title, s.claude_title, s.project_id, p.display_name AS project_name "
    "FROM sessions s LEFT JOIN projects p ON p.id = s.project_id "
)

Resolver = Callable[[sqlite3.Connection], Optional[Dict[str, Any]]]


@dataclass(frozen=True)
class JobResult:

    state: str
    detail: str = ""


def default_paths() -> tuple[Path, Path]:
    from src.config import settings
    from src.core.db import db_path_for

    state = settings.get_state_dir()
    return state, db_path_for(state)


def facts_of(row: Dict[str, Any]) -> Dict[str, Any]:
    facts = {"working_dir": row.get("working_dir"), "project_name": row.get("project_name"),
             "wrapper": row.get("agent_type"), "title": row.get("title") or row.get("claude_title")}
    return {k: v for k, v in facts.items() if v is not None}


def fetch_row(conn: sqlite3.Connection, *, row_id: Optional[int] = None,
              session_uuid: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if row_id is not None:
        found = conn.execute(ROW_SQL + "WHERE s.id = ?", (row_id,)).fetchone()
    else:
        found = conn.execute(ROW_SQL + "WHERE s.session_uuid = ?", (session_uuid,)).fetchone()
    return dict(found) if found is not None else None


def conversation_of(row: Dict[str, Any], conversation_id: Optional[str] = None) -> Optional[str]:
    """The local conversation id a session row's milestone is about, or None when it has none.

    ``conversation_id`` names a conversation that is no longer the row's current one (the pre-/clear
    conversation); by default the row's ``claude_session_uuid`` is used. A remote row has none.
    Example: conversation_of({"claude_session_uuid": "c1"})  # 'c1'
    """
    conv = conversation_id or row.get("claude_session_uuid")
    if not conv or (row.get("host_key") or "local") != "local":
        return None
    return str(conv)


def enqueue(event: str, resolve: Resolver, *, conversation_id: Optional[str] = None,
            child_conversation_id: Optional[str] = None, record_lineage: bool = True,
            state_dir: Optional[Path] = None, db_path: Optional[Path] = None, log_label: str = "") -> Optional[Future]:
    from src.core.db import connect
    from src.core.pipeline import runtime
    from src.core.pipeline.lifecycle import UNRESOLVED

    outer: Future = Future()
    if not record_lineage:
        outer.set_result(JobResult(STATE_DONE))
        return outer
    if state_dir is None or db_path is None:
        state_dir, db_path = default_paths()
    try:
        engine = runtime.ensure(state_dir, db_path)
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        logger.error("pipeline_enqueue_failed", save_event=event, label=log_label, error=str(exc))
        return None
    if engine.db_path != Path(db_path):
        logger.error("pipeline_enqueue_other_database", save_event=event, label=log_label)
        return None

    def resolve_row():
        with closing(connect(engine.db_path, create=False)) as conn:
            row = resolve(conn)
        found = conversation_of(row, conversation_id) if row else None
        if found is None:
            return None
        return found, {"session_uuid": row.get("session_uuid"), "child_conversation_id": child_conversation_id,
                       "family": row.get("agent_family"), "facts": facts_of(row)}

    def settle(done: Future) -> None:
        answer = done.result()
        if answer in (UNRESOLVED, "dropped"):
            outer.set_result(JobResult(STATE_REFUSED, detail=answer))
        else:
            outer.set_result(JobResult(STATE_DONE))

    engine.write_milestone(event, "", time.time(), resolve=resolve_row).add_done_callback(settle)
    return outer


def schedule_for_uuid(session_uuid: str, reason: str, *, state_dir: Optional[Path] = None,
                      db_path: Optional[Path] = None):
    return enqueue(reason, lambda c: fetch_row(c, session_uuid=session_uuid), state_dir=state_dir, db_path=db_path,
                   log_label=f"{reason}:{session_uuid}")


def _resolve_instance(conn: sqlite3.Connection, socket: str, name: str,
                      epoch: Optional[int], host_key: str) -> Optional[Dict[str, Any]]:
    from src.core.session_store import identity_for_instance, identity_for_live_name

    ident = (identity_for_instance(conn, socket=socket, name=name, epoch=epoch, host_key=host_key)
             if epoch is not None
             else identity_for_live_name(conn, socket=socket, name=name, host_key=host_key))
    return fetch_row(conn, row_id=ident["id"]) if ident else None


def schedule_for_instance(socket: Optional[str], name: Optional[str], epoch: Optional[int],
                          reason: str, *, host_key: str = "local",
                          state_dir: Optional[Path] = None, db_path: Optional[Path] = None):
    if not socket or not name:
        return None
    return enqueue(reason, lambda c: _resolve_instance(c, socket, name, epoch, host_key), state_dir=state_dir,
                   db_path=db_path, log_label=f"{reason}:{name}")


def schedule_for_conversation(conversation_id: str, session_uuid: str, reason: str, *,
                              child_conversation_id: Optional[str] = None, record_lineage: bool = True,
                              state_dir: Optional[Path] = None, db_path: Optional[Path] = None):
    return enqueue(reason, lambda c: fetch_row(c, session_uuid=session_uuid), state_dir=state_dir, db_path=db_path,
                   log_label=f"{reason}:{conversation_id}", conversation_id=conversation_id,
                   child_conversation_id=child_conversation_id, record_lineage=record_lineage)
