
from __future__ import annotations

from typing import Any, Dict, FrozenSet, NoReturn, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.api.error_response import api_error, refusal_error
from src.api.remote_route_guard import refuse_remote
from src.core.timeline import bodies, cursor, gate, resolve, service
from src.core.timeline.model import Kind

router = APIRouter(prefix="/sessions/{session}/timeline", tags=["timeline"], dependencies=[Depends(require_auth)])

MAX_LIMIT: int = 500


def _kinds(text: Optional[str]) -> Optional[FrozenSet[Kind]]:
    if not text:
        return None
    return frozenset(Kind(name.strip()) for name in text.split(",") if name.strip())


def _refuse(exc: BaseException) -> NoReturn:
    from src.core.bookmarks.errors import BookmarkError  # noqa: PLC0415

    if isinstance(exc, BookmarkError):
        raise refusal_error(exc) from exc
    if isinstance(exc, gate.TimelineOff):
        raise api_error(409, "timeline_off", exc) from exc
    if isinstance(exc, (cursor.CursorError, bodies.EventIdError, ValueError)):
        raise api_error(422, "invalid_request", exc) from exc
    if isinstance(exc, bodies.StaleEvent):
        raise api_error(409, "conflict", exc) from exc
    if isinstance(exc, (service.NoConversation, service.UnknownConversation, service.UnknownFile, service.UnknownTurn)):
        raise api_error(404, "not_found", exc) from exc
    raise api_error(409, "transcript_unavailable", exc) from exc


async def _read(request: Request, session: str, fn: Any, **kwargs: Any) -> Dict[str, Any]:
    from src.core.bookmarks.errors import BookmarkError  # noqa: PLC0415

    try:
        gate.require_on()
        manager = request.app.state.session_manager
        refuse_remote(manager, session, "the timeline read")
        publisher = getattr(request.app.state, "listing_publisher", None)
        listing = resolve.pushed_listing(publisher, manager) if publisher is not None else None
        resolved = await resolve.resolve(manager, session, listing)
        return await run_in_threadpool(fn, resolved, **kwargs)
    except HTTPException:
        raise
    except (gate.TimelineOff, cursor.CursorError, bodies.EventIdError, bodies.StaleEvent, ValueError, OSError, BookmarkError,
            service.NoConversation, service.UnknownConversation, service.UnknownFile, service.UnknownTurn) as exc:
        _refuse(exc)


@router.get("/state")
async def timeline_state(request: Request, session: str) -> Dict[str, Any]:
    """The session's state: the transcript tier (open turn, last turn end, open agents, queued re-invoke, newest times) and, for a
    live session, the lights' answer (``live``). ``source`` says whether the hot driver held the file (``hot``) or it was folded now.

    Inputs: request; session. Output: dict. 409 ``timeline_off``, 404 ``session_not_found``, 409 ``not_claude``.
    Example: GET /api/v1/sessions/ses_1/timeline/state -> {"conv": "...", "transcript": {"open_agents": 1, ...}, "live": {...}}
    """
    return await _read(request, session, service.state)


@router.get("/events")
async def timeline_events(
    request: Request, session: str,
    after: Optional[str] = Query(None, description="a cursor <conv>:<file_key>:<offset>:<serial>; reads forward after it"),
    before_turn: Optional[int] = Query(None, ge=0, description="a turn id: the turns older than it (newest page when absent)"),
    limit: Optional[int] = Query(None, ge=1, le=MAX_LIMIT, description="events for a forward page, turns for a backward one"),
    kinds: Optional[str] = Query(None, description="comma separated event kinds"),
    thread: Optional[str] = Query(None, description="main, side, wf:<id> or agent:<id> (an agent thread reads that agent's file)"),
    turn: Optional[int] = Query(None, ge=0, description="one turn's events, by turn id"),
    level: Optional[int] = Query(None, ge=1, le=4, description="1 talk, 2 work (default), 3 trace, 4 raw (developer mode only)"),
    conv: Optional[str] = Query(None, description="a conversation of this session; the current one by default"),
    include_abandoned: bool = Query(False, description="also the lines of branches a rewind left behind, each flagged abandoned"),
) -> Dict[str, Any]:
    """A page of the session's typed events and the cursor to come back with.

    Forward (``after``): the complete lines after the cursor, at most 1 MiB or 500 events; a rewritten or truncated file answers
    ``reset`` (``file_rewritten`` or ``truncated``) and no events, and the client reads again from the start. Backward (``before_turn``,
    or no cursor at all): the newest turns through the cold index, 8 MiB at most; ``indexing: {pct}`` while the index has not covered
    the conversation (the newest window of the file is answered meanwhile). A line over the read budget is ONE stub event; a turn over
    8 MiB answers its prompt, its last reply and a summary in ``chips`` (open it with ``turn=``). A rewind hides the abandoned branch behind
    one ``rewind`` divider; ``include_abandoned=true`` shows it, each event flagged ``abandoned``. Answer:
    ``{session_uuid, conv, file_key, events, next, next_before, end, reset, indexing, size, chips}``.
    Example: GET /api/v1/sessions/ses_1/timeline/events?after=abc:main:1204:u-1&level=3
    """
    try:
        wanted = _kinds(kinds)
    except ValueError as exc:
        raise api_error(422, "invalid_request", exc) from exc
    return await _read(request, session, service.events, after=after, before_turn=before_turn, limit=limit, kinds=wanted,
                       thread=thread, turn=turn, level=level, conv=conv, include_abandoned=include_abandoned)


@router.get("/events/{event_id}")
async def timeline_event(request: Request, session: str, event_id: str) -> Dict[str, Any]:
    """One event with its full text or tool body, ANSI stripped and redacted whole, cut to 64 KB (``withheld`` for thinking).

    Inputs: request; session; event_id (``<conv>:<file_key>:<offset>:<n>:<serial8>``). Output: dict. 409 ``conflict`` when the id
    names a line that was rewritten, 422 for a malformed id.
    Example: GET /api/v1/sessions/ses_1/timeline/events/abc:main:1204:0:b0010000
    """
    return await _read(request, session, service.body, event_id=event_id)


@router.get("/turns")
async def timeline_turns(request: Request, session: str, before: Optional[int] = Query(None, ge=0),
                         limit: Optional[int] = Query(None, ge=1, le=200)) -> Dict[str, Any]:
    """The cold index's turns of the current conversation, newest first (positions, counts and kind names only).

    Inputs: request; session; before (a turn id); limit. Output: ``{turns, next_before, indexing}``.
    Example: GET /api/v1/sessions/ses_1/timeline/turns?limit=20
    """
    return await _read(request, session, service.turns, before=before, limit=limit)


@router.get("/threads")
async def timeline_threads(request: Request, session: str) -> Dict[str, Any]:
    """The cold index's tasks of the current conversation: agents, workflows, shells, monitors and the newest todo marker.

    Inputs: request; session. Output: ``{threads, todo, indexing}``.
    Example: GET /api/v1/sessions/ses_1/timeline/threads
    """
    return await _read(request, session, service.threads)
