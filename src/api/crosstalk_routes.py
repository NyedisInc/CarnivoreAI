
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query, Request

from src.api.error_response import api_error
from src.api.auth import require_auth
from src.core.crosstalk import directory
from src.core.mcp.protocol import BatchView

router = APIRouter(prefix="/crosstalk", tags=["crosstalk"], dependencies=[Depends(require_auth)])


@router.get("/agents")
async def list_agents(
    request: Request,
    q: Optional[str] = Query(None, description="a name: '@Cv-Misc UI', case, spaces and dashes ignored"),
    provider: Optional[str] = Query(None, description="agent family filter, e.g. claude or codex"),
    include_remote: bool = True,
    limit: int = Query(25, ge=1, le=100),
) -> dict:
    """Agents on this computer and the paired ones, ranked against ``q`` when given.

    Output: {"agents": [card], "match": tier | None, "ambiguous": bool, "truncated": bool, "query": str | None}.
    """
    view = BatchView(request.app.state.session_manager, request.app)
    return await directory.lookup(view, query=q, provider=provider, include_remote=include_remote,
                                  include_self=True, limit=limit)


from pydantic import BaseModel, Field
from src.core.crosstalk import bus, store
from src.core.mcp.caller import AgentCaller


class SendRequest(BaseModel):
    """An owner-authenticated crosstalk send."""

    to: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=store.MAX_TEXT)
    thread: Optional[str] = Field(default=None, max_length=100)
    in_reply_to: Optional[str] = Field(default=None, max_length=100)
    expect_reply: bool = False
    task_item: Optional[int] = Field(default=None, ge=1, description="Task Manager item id this message concerns")


@router.get('/messages')
async def messages(session: str = Query(..., min_length=1), since: float = Query(0, ge=0),
                   limit: int = Query(200, ge=1, le=500)) -> dict:
    """Owner's exact session history, including closed rows, for inline cards."""
    import asyncio
    return {'messages': await asyncio.to_thread(store.owner_messages, session, since=since, limit=limit)}


@router.post('/messages')
async def send_message(body: SendRequest, request: Request) -> dict:
    """Send as the authenticated owner through the shared bus; an owner send grants its pair."""
    from src.core.mcp.common import ToolError
    view = BatchView(request.app.state.session_manager, request.app)
    caller = AgentCaller(session_id='owner', tmux_name='owner', current_session_id='owner', token_name='owner')
    try:
        return await bus.send(view, caller, to=body.to, text=body.text, thread=body.thread,
                              in_reply_to=body.in_reply_to, expect_reply=body.expect_reply,
                              owner_approved=True, task_item=body.task_item)
    except ToolError as exc:
        raise api_error(409, 'crosstalk_refused', exc) from exc


from src.core.crosstalk import history


@router.get('/threads')
async def threads(session: Optional[str] = Query(None, min_length=1, max_length=200,
                                                 description="a session id (ses_ or adopted:) or session_uuid"),
                  session_row: Optional[int] = Query(None, ge=1, description="sessions.id, resolved to its session_uuid"),
                  project: Optional[int] = Query(None, ge=1, description="projects.id; a thread one side belongs to"),
                  before: Optional[float] = Query(None, ge=0, description="only threads last active before this epoch"),
                  limit: int = Query(history.THREADS_LIMIT, ge=1, le=history.THREADS_MAX)) -> dict:
    """The owner's past crosstalk threads, newest activity first (issue #1498); the MCP ``crosstalk_threads_list`` reads the same.

    Output: {"threads": [{"thread", "participants", "message_count", "last_at", "first_at", "last_preview",
      "last_sender_key", "last_status"}], "next_before"}; text redacted. Re-read on the ``crosstalk`` resource topic.
    """
    import asyncio
    return await asyncio.to_thread(history.list_threads, session=session, session_row=session_row, project=project,
                                   before=before, limit=limit)


@router.get('/threads/{thread}/messages')
async def thread_messages(thread: str, before: Optional[float] = Query(None, ge=0),
                          limit: int = Query(history.MESSAGES_LIMIT, ge=1, le=history.MESSAGES_MAX)) -> dict:
    """One thread's messages, oldest first, owner-only (issue #1498); 404 for a thread with no rows.

    Output: {"thread", "messages": [row], "next_before"}; text redacted. The MCP ``crosstalk_thread`` reads the same
    for a participant.
    """
    import asyncio
    try:
        return await asyncio.to_thread(history.thread_messages, thread, before=before, limit=limit)
    except history.HistoryError as exc:
        raise api_error(404, 'crosstalk_thread_unknown', exc, thread=thread) from exc


@router.get('/task-items/{task_item}/messages')
async def task_item_messages(task_item: int = Path(..., ge=1, description="a Task Manager item id"),
                             limit: int = Query(history.MESSAGES_LIMIT, ge=1, le=history.MESSAGES_MAX)) -> dict:
    """The crosstalk trail of one Task Manager item (#1907), oldest first, owner-only.

    Output: {"task_item", "messages": [{"id", "thread", "sender_name", "receiver_name", "created_at", "status",
      "preview"}]}; preview is the first line, redacted. Re-read on the ``crosstalk`` resource topic.
    """
    import asyncio
    return await asyncio.to_thread(history.task_item_trail, task_item, limit=limit)
