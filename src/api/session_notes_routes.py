
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api.error_response import api_error
from src.api.peer_auth import require_peer_sessions
from src.core import session_change_notice, session_notes_store as store
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.hosts.identity import parse_remote_session_id
from src.core.session_group_membership_migrate import resolve_session_uuid
from src.models import WSMessageType

logger = structlog.get_logger()

router = APIRouter()


class SessionNoteResponse(BaseModel):
    """One session's note as the browser receives it.

    ONE SHAPE FOR THE READ, THE WRITE AND THE 409, which is what lets a
    client fold a conflict by replacing what it holds rather than by
    parsing a second schema.
    """

    status: str = Field(
        ...,
        description=(
            "'committed' | 'unchanged' | 'stale_revision' | 'rejected_invalid'. "
            "A read reports 'unchanged': it moved nothing."
        ),
    )
    revision: int = Field(
        ..., description="The CURRENT stored revision. 0 when nothing is stored."
    )
    body: str = Field(
        ...,
        description="The markdown SOURCE, stored and returned verbatim, never rendered.",
    )
    updated_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC of the last commit, or null when nothing is stored.",
    )
    detail: Optional[str] = Field(
        default=None, description="Why a refusal happened, safe to show a user."
    )


class UpdateSessionNoteRequest(BaseModel):
    """A whole new note, plus the revision the caller believes is current.

    ``body`` is the complete markdown, not a patch: a note is small, and a
    delta against a revision the server may have moved past is exactly
    the thing the revision check exists to refuse.
    """

    body: str = Field(..., description="The whole markdown source.")
    expected_revision: int = Field(
        ...,
        ge=0,
        description=(
            "The revision the caller read. 0 means 'I believe nothing is "
            "stored'. REQUIRED: a write with no base is a write that can "
            "overwrite another computer without knowing it."
        ),
    )


def _db_path():
    from src.config import settings

    return db_path_for(settings.get_state_dir())


def _resolve(conn: Any, session_name: str) -> Optional[str]:
    parsed = parse_remote_session_id(session_name)
    if parsed is not None:
        return resolve_session_uuid(conn, parsed[1], host_key=parsed[0])
    return resolve_session_uuid(conn, session_name)


def _read(session_name: str) -> store.NoteResult:
    with closing(connect(_db_path(), create=False)) as conn:
        session_uuid = _resolve(conn, session_name)
        if session_uuid is None:
            raise KeyError(session_name)
        return store.read_note(conn, session_uuid)


def _write(session_name: str, body: str, expected_revision: int):
    with closing(connect(_db_path(), create=False)) as conn:
        session_uuid = _resolve(conn, session_name)
        if session_uuid is None:
            raise KeyError(session_name)
        with conn:
            return session_uuid, store.write_note(
                conn, session_uuid, body, expected_revision
            )


def _refuse_unreadable(exc: Exception) -> HTTPException:
    return api_error(503, "datastore_unavailable", exc, step="session_notes")


def _note_changed_frame(
    session_name: str, session_uuid: str, revision: int
) -> Dict[str, Any]:
    return {
        "type": WSMessageType.SESSION_NOTE_CHANGED,
        "tmux_session": session_name,
        "session_uuid": session_uuid,
        "revision": revision,
    }


@router.get(
    "/sessions/{session_name}/note",
    response_model=SessionNoteResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_session_note(session_name: str) -> SessionNoteResponse:
    """This session's markdown note, or the empty note at revision 0.

    Description: an absent note reads as ``{"body": "", "revision": 0,
      "updated_at": null}`` and creates nothing. That is the one place in
      this feature where absent maps to a value, and it is deliberate: an
      empty notepad is exactly and completely what "nothing written yet"
      is, and revision 0 gives the first save a real base to send so it
      goes through the same concurrency check as every later one.
    Inputs: session_name (str, path) - the tmux session name.
    Output: SessionNoteResponse.
    Raises: HTTPException - 404 no such stored session, 503 the datastore
      cannot be read.
    """
    path = _db_path()
    if not path.exists():
        raise HTTPException(
            status_code=503, detail="datastore has not been created yet"
        )
    try:
        result = await run_in_threadpool(_read, session_name)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"no stored session named {session_name!r}"
        )
    except (DatastoreUnreadableError, store.SessionNotesUnavailable) as exc:
        logger.info("session_note_unavailable", reason=str(exc))
        raise _refuse_unreadable(exc)
    except OSError as exc:
        logger.warning("session_note_read_failed", error=str(exc))
        raise _refuse_unreadable(exc)
    return SessionNoteResponse(**result.as_payload())


@router.put(
    "/sessions/{session_name}/note",
    response_model=SessionNoteResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def put_session_note(
    request: Request, session_name: str, body: UpdateSessionNoteRequest
) -> SessionNoteResponse:
    """Replace this session's note, from the revision the caller read.

    Description: the write is refused unless ``expected_revision`` is the
      stored one. A refusal is a 409 whose body carries the current
      revision AND the current note, so the caller reconciles against
      real content instead of retrying into the same conflict. An
      identical body is a 200 reporting ``unchanged`` and moves no
      revision, so other clients are not made to re-read for a change
      that did not happen. An EMPTY body is a real note: clearing a
      notepad is something a person does on purpose.
    Inputs: request (Request) - for the event hub; session_name (str,
      path) - the tmux session name; body (UpdateSessionNoteRequest).
    Output: SessionNoteResponse.
    Raises: HTTPException - 404 no such stored session, 409 stale
      revision (body carries the current note), 413 over the size cap,
      503 the datastore cannot be written.
    """
    path = _db_path()
    if not path.exists():
        raise HTTPException(
            status_code=503, detail="datastore has not been created yet"
        )
    try:
        session_uuid, result = await run_in_threadpool(
            _write, session_name, body.body, body.expected_revision
        )
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"no stored session named {session_name!r}"
        )
    except (DatastoreUnreadableError, store.SessionNotesUnavailable) as exc:
        logger.info("session_note_unavailable", reason=str(exc))
        raise _refuse_unreadable(exc)
    except OSError as exc:
        logger.warning("session_note_write_failed", error=str(exc))
        raise _refuse_unreadable(exc)

    if result.status == store.STALE_REVISION:
        raise HTTPException(status_code=409, detail=result.as_payload())
    if result.status == store.REJECTED_INVALID:
        raise HTTPException(status_code=413, detail=result.as_payload())

    if result.status == store.COMMITTED:
        session_change_notice.publish(
            request.app.state,
            _note_changed_frame(session_name, session_uuid, result.revision),
        )
    return SessionNoteResponse(**result.as_payload())
