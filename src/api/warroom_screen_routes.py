
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.api import peer_auth
from src.api.peer_auth import require_peer_sessions
from src.api.peer_ws_auth import local_session_id
from src.core.db import DatastoreUnreadableError
from src.core.federation import peer_forward, peer_listing
from src.core.federation.peer_fanout import is_peer_call
from src.core.hosts.identity import is_remote_backend, parse_remote_session_id
from src.core.warroom.peer_screens import PEER_TOTAL_SECONDS, PeerAsk, PeerGroup, ask_peers
from src.core.warroom.screens import capture_many

logger = structlog.get_logger()
router = APIRouter()

MAX_SCREENS_PER_CALL = 40


class ScreenAsk(BaseModel):
    """One session the wall shows, with the hash of the screen it already holds."""

    id: str = Field(..., max_length=200, description="session id: a ses_ id or adopted:<tmux name>")
    hash: Optional[str] = Field(None, max_length=64, description="hash of the screen the client has; same hash answers nothing")


class ScreensRequest(BaseModel):
    """The batch."""

    items: List[ScreenAsk] = Field(..., max_length=MAX_SCREENS_PER_CALL)


class ScreenAnswer(BaseModel):
    """One pane. ``status`` is ok, gone (no such pane), unsupported (no screen to show), older (the paired computer runs
    a release without this route) or unreachable (the paired computer did not answer; the wall keeps its paint)."""

    status: str
    cols: int = 0
    rows: int = 0
    hash: str = ""
    screen: str = ""


class ScreensResponse(BaseModel):
    """Answers by session id; a pane whose hash matched the request is ABSENT."""

    screens: Dict[str, ScreenAnswer]


@router.post("/warroom/screens", response_model=ScreensResponse, dependencies=[Depends(require_peer_sessions)])
async def post_warroom_screens(request: Request, body: ScreensRequest) -> ScreensResponse:
    """The visible screen (with color escapes, no scrollback) of up to 40 sessions.

    Description: resolves each id against the registry to its STORED tmux name (never derived from the id), reads the
      local panes concurrently on this app's own socket, and leaves out any pane whose hash equals the asked one. A
      missing or dead pane answers ``gone``; a paired computer's session (``remote:peer-...`` or a remote backend)
      answers ``unsupported`` and the tile keeps its card.
    Inputs: request (Request); body (ScreensRequest).
    Output: ScreensResponse. Never a 500 for one bad pane.
    Example: POST {"items":[{"id":"ses_1","hash":"ab12"}]} -> {"screens":{"ses_1":{"status":"ok","cols":80,"rows":24,...}}}
    """
    manager = request.app.state.session_manager
    registry = manager._registry
    backends = registry.backends
    out: Dict[str, ScreenAnswer] = {}
    names: Dict[str, Optional[str]] = {}
    remote_ids: List[str] = []
    for ask in body.items:
        sid = ask.id if ask.id in backends else local_session_id(registry, ask.id)
        backend = backends.get(sid)
        if is_peer_call(request) and backend is not None and registry.is_hidden(sid):
            out[ask.id] = ScreenAnswer(status="unsupported")
            continue
        if parse_remote_session_id(ask.id) is not None or is_remote_backend(backend):
            if is_peer_call(request) or parse_remote_session_id(ask.id) is None:
                out[ask.id] = ScreenAnswer(status="unsupported")
            else:
                remote_ids.append(ask.id)
        else:
            names[ask.id] = getattr(backend, "tmux_session", None) if backend is not None else None
    asked = {ask.id: ask.hash for ask in body.items}
    local, remote = await asyncio.gather(
        capture_many(manager._tmux_socket_name(), names), _ask_remote(remote_ids, asked))
    for sid, shot in local.items():
        if shot.status == "ok" and shot.hash == asked.get(sid):
            continue
        out[sid] = ScreenAnswer(status=shot.status, cols=shot.cols, rows=shot.rows, hash=shot.hash, screen=shot.screen)
    answers, unresolved = remote
    out.update({rid: ScreenAnswer(status="unsupported") for rid in unresolved})
    out.update({rid: ScreenAnswer(**ans) for rid, ans in answers.items()})
    return ScreensResponse(screens=out)


def _group_by_peer(remote_ids: List[str], asked: Dict[str, Optional[str]]) -> List[PeerGroup]:
    groups: Dict[str, PeerGroup] = {}
    try:
        conn = peer_auth.open_db()
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("warroom_peer_screens_db_unreadable", error=type(exc).__name__)
        return []
    with closing(conn):
        for rid in remote_ids:
            target = peer_forward.resolve(conn, rid)
            if target is None:
                continue
            peer_id = peer_listing.owner_session_id(target.peer.key, target.name) or target.name
            group = groups.setdefault(target.peer.key, PeerGroup(target.peer.peer_install_id, target.peer.key, []))
            group.asks.append(PeerAsk(rid, peer_id, asked.get(rid)))
    return list(groups.values())


async def _ask_remote(remote_ids: List[str], asked: Dict[str, Optional[str]]) -> Tuple[Dict[str, dict], List[str]]:
    if not remote_ids:
        return {}, []
    groups = await asyncio.to_thread(_group_by_peer, remote_ids, asked)
    resolved = {a.remote_id for g in groups for a in g.asks}
    try:
        answers = await asyncio.wait_for(ask_peers(groups), PEER_TOTAL_SECONDS)
    except asyncio.TimeoutError:
        logger.info("warroom_peer_screens_total_timeout", peers=len(groups))
        answers = {rid: {"status": "unreachable"} for rid in resolved}
    return answers, [rid for rid in remote_ids if rid not in resolved]
