
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.core.pack.identity.home import ProjectMovedAway
from src.api.auth import require_auth
from src.config import settings
from src.core import session_fork
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.session_conversations import view
from src.core.session_label import label_from_tmux_name
from src.core.session_name_claim import sanitize_tmux_name
from src.core.session_transcript_presence import CONVERSATION_PRESENT, conversation_presence
from src.api.error_response import api_error

logger = structlog.get_logger()
router = APIRouter(tags=["session-conversations"], dependencies=[Depends(require_auth)])


class ConversationItem(BaseModel):
    """One conversation of a session."""

    conversation_id: str
    current: bool
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    ended_reason: Optional[str] = Field(None, description="previous: the lineage edge's kind (clear, fork, resume, switch, compact_continue); current: the index row's reason, null while open")
    link_basis: Optional[str] = Field(None, description="previous: recorded, inferred_fork_pointer or inferred_unique_candidate; null on the current entry")
    first_prompt: str = ""
    summary: Optional[str] = None
    transcript_on_disk: bool


class ConversationList(BaseModel):
    """A session's current conversation and every ended one, newest first."""

    session_uuid: str
    current: Optional[ConversationItem] = None
    previous: List[ConversationItem] = Field(default_factory=list)
    previous_count: int = 0


class Counts(BaseModel):
    """``by_session`` maps a session uuid to how many ended conversations it has (sessions with none are absent)."""

    by_session: Dict[str, int] = Field(default_factory=dict)


class LatestLine(BaseModel):
    """One session's latest line: the first prompt of its newest conversation."""

    text: str
    at: Optional[str] = None
    kind: str = Field(description="first_prompt")


class LatestLines(BaseModel):
    """``by_session`` maps a session uuid to its latest line; a session with no stored prompt is absent."""

    by_session: Dict[str, LatestLine] = Field(default_factory=dict)


class ResumeResponse(BaseModel):
    """The new session started on an earlier conversation."""

    success: bool = True
    session: dict = Field(default_factory=dict)
    parent_session_id: Optional[int] = None
    lineage_recorded: bool = False
    detail: Optional[str] = None


def _db_path():
    return db_path_for(settings.get_state_dir())


def _corpus_root():
    from src.core.claude_transcript_correlate import default_projects_dir

    return default_projects_dir()


def _read(fn):
    path = _db_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="no datastore yet")
    try:
        with closing(connect(path, create=False)) as conn:
            return fn(conn)
    except DatastoreUnreadableError as exc:
        raise api_error(503, "datastore_unavailable", exc) from exc


@router.get("/sessions/{session_uuid}/conversations", response_model=ConversationList)
async def list_conversations(session_uuid: str) -> ConversationList:
    """The session's current conversation and every earlier one, newest first, with summary."""
    def build(conn) -> Optional[Dict[str, Any]]:
        return view.build(conn, session_uuid, corpus_root=_corpus_root())

    found = await run_in_threadpool(_read, build)
    if found is None:
        raise HTTPException(status_code=404, detail="no such session")
    return ConversationList(**found)


@router.get("/sessions/latest-lines", response_model=LatestLines)
async def latest_lines() -> LatestLines:
    """Every session's latest line in one read (the stored first prompt); opens no transcript."""
    def lines(conn) -> Dict[str, Dict[str, str]]:
        return view.latest_lines(conn)

    return LatestLines(by_session=await run_in_threadpool(_read, lines))


@router.get("/session-conversations/counts", response_model=Counts)
async def conversation_counts() -> Counts:
    """How many earlier conversations each session has (one query, for the page's row badges)."""
    def counts(conn) -> Dict[str, int]:
        return view.previous_counts(conn)

    return Counts(by_session=await run_in_threadpool(_read, counts))


def _resume_source(conn, session_uuid: str, conversation_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT id, claude_session_uuid, working_dir, title, tmux_name, agent_type, model, launch_record "
                       "FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such session")
    if conversation_id != row["claude_session_uuid"] and conversation_id not in view.conversation_ids(conn, session_uuid):
        raise HTTPException(status_code=404, detail="that conversation does not belong to this session")
    if conversation_presence(conversation_id, working_dir=row["working_dir"], corpus_root=_corpus_root()).outcome != CONVERSATION_PRESENT:
        raise HTTPException(status_code=409, detail="that conversation's transcript is not on disk")
    return dict(row)


@router.post("/sessions/{session_uuid}/conversations/{conversation_id}/resume", response_model=ResumeResponse, status_code=201)
async def resume_conversation(request: Request, session_uuid: str, conversation_id: str) -> ResumeResponse:
    """Start a NEW session resuming an earlier conversation; the current session is not touched.

    Description: ``--resume <conversation> --fork-session`` so the earlier transcript is copied, never
      appended to. 404 unknown session or foreign conversation; 409 no transcript on disk;
      201 started, ``lineage_recorded`` says whether the parent link landed.
    """
    source = await run_in_threadpool(_read, lambda conn: _resume_source(conn, session_uuid, conversation_id))
    from src.api.launch_profile_errors import refuse_gone_profile

    refuse_gone_profile(settings, source["agent_type"], source["launch_record"])
    manager = request.app.state.session_manager
    label = session_fork.fork_label(source["title"] or label_from_tmux_name(source["tmux_name"]))
    try:
        forked = await session_fork.spawn_fork_child(
            manager, source=source, label=label, project_name=sanitize_tmux_name(label) or label,
            agent_extra_args=session_fork.fork_arguments(conversation_id), db_path=_db_path(),
            socket=manager.tmux_socket_name(), resumed_conversation=conversation_id)
    except ProjectMovedAway:
        raise
    except Exception as exc:  # noqa: BLE001
        raise api_error(500, "session_resume_failed", exc, session_uuid=session_uuid) from exc
    child, recorded = forked.session, forked.recorded
    if forked.stamp_error is not None:
        logger.warning("conversation_resume_lineage_unrecorded", session_uuid=session_uuid,
                       error=str(forked.stamp_error))
    return ResumeResponse(session=child.model_dump(), parent_session_id=source["id"], lineage_recorded=recorded,
                          detail=None if recorded else "the session started, but its parent link could not be recorded")
