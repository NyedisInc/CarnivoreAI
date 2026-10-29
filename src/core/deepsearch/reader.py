
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.db import DatastoreUnreadableError
from src.core.deepsearch import context, context_read, grouped, peer_air_gap, status, suggest
from src.core.deepsearch.cache import db as cache_db
from src.core.federation import peer_deepsearch

logger = structlog.get_logger()


class ConversationsUnavailable(Exception):
    pass


class InvalidSearch(ValueError):
    pass


class ContextNotFound(LookupError):
    pass


class ConversationIndex:

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = Path(state_dir)

    def _read(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        try:
            with closing(cache_db.reader(self._state_dir)) as conn:
                return work(conn)
        except (DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
            logger.error("deepsearch_index_unavailable", error_type=type(exc).__name__, error=str(exc)[:300])
            raise ConversationsUnavailable(f"{type(exc).__name__}: {exc}") from exc

    async def search(self, q: str, *, kinds: Optional[List[str]] = None, project: Optional[str] = None,
                     conversation_id: Optional[str] = None, limit: int = 20, offset: int = 0,
                     per_group: int = 3, peers: bool = False, for_peer: bool = False) -> Dict[str, Any]:
        def work(conn: sqlite3.Connection) -> Dict[str, Any]:
            gate = peer_air_gap.load_gate(self._state_dir) if for_peer else None
            return grouped.search_grouped(conn, self._state_dir, q, kinds=kinds, project=project,
                                          conversation_id=conversation_id, limit=limit, offset=offset,
                                          per_group=per_group, peer_gate=gate)

        try:
            local = asyncio.to_thread(self._read, work)
            if peers and peer_deepsearch.peers_wanted(project, offset):
                return await peer_deepsearch.with_peers(self._state_dir, local, q=q, kinds=kinds, project=project,
                                                        conversation_id=conversation_id, limit=limit, per_group=per_group)
            return await local
        except grouped.InvalidKinds as exc:
            raise InvalidSearch(str(exc)) from exc

    async def search_peers(self, q: str, *, kinds: Optional[List[str]] = None, project: Optional[str] = None,
                           conversation_id: Optional[str] = None, limit: int = 20, offset: int = 0,
                           per_group: int = 3) -> Dict[str, Any]:
        if not peer_deepsearch.peers_wanted(project, offset):
            return {"groups": [], "total_conversations": 0, "total_matches": 0, "peer_unavailable": []}
        return await peer_deepsearch.peers_only(self._state_dir, q=q, kinds=kinds, project=project,
                                                conversation_id=conversation_id, limit=limit, per_group=per_group)

    async def suggest(self, prefix: str, limit: int = 8) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self._read, lambda conn: suggest.suggest_terms(conn, prefix, limit))
        except suggest.InvalidPrefix as exc:
            raise InvalidSearch(str(exc)) from exc

    async def context(self, conversation_id: str, *, file_kind: str = "conversation", line: Optional[int] = None,
                      at: Optional[str] = None, before_line: Optional[int] = None, after_line: Optional[int] = None,
                      before: int = 20, after: int = 20, host_key: Optional[str] = None,
                      for_peer: bool = False) -> Dict[str, Any]:
        try:
            return await context_read.read(self._state_dir, self._read, conversation_id, file_kind=file_kind, line=line, at=at,
                                           before_line=before_line, after_line=after_line, before=before, after=after,
                                           host_key=host_key, for_peer=for_peer)
        except context.ContextNotFound as exc:
            raise ContextNotFound(str(exc)) from exc
        except context_read.PeerContextUnavailable as exc:
            raise ConversationsUnavailable(f"the computer did not answer: {exc.reason}") from exc
        except peer_air_gap.AirGapUnreadable as exc:
            raise ConversationsUnavailable("the project registry cannot be read") from exc
        except OSError as exc:
            raise ConversationsUnavailable(f"the transcript cannot be read: {type(exc).__name__}") from exc

    async def status(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self._read, lambda conn: status.index_status(self._state_dir))


def default_index() -> ConversationIndex:
    from src.config import settings  # noqa: PLC0415

    return ConversationIndex(Path(settings.get_state_dir()))
