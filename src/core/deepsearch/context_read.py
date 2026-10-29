
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.core.deepsearch import constants as K
from src.core.deepsearch import context, grouped, hit_bookmarks, peer_air_gap
from src.core.deepsearch import rules as rules_mod
from src.core.federation import peer_deepsearch


class PeerContextUnavailable(RuntimeError):
    """The paired computer could not give the window; ``reason`` is the link's word for why (``timeout``, ``http_404``...)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _local(conn: sqlite3.Connection, state_dir: Path, conversation_id: str, file_kind: str, for_peer: bool,
           anchor: Dict[str, Any], before: int, after: int) -> Dict[str, Any]:
    gate = peer_air_gap.load_gate(state_dir) if for_peer else None
    file = context.find_file(conn, conversation_id, file_kind)
    if file is None:
        raise context.ContextNotFound("that conversation is not in the index")
    if gate is not None and gate.active and conversation_id not in gate.admitted(conn, grouped.describe(conn, [conversation_id])):
        raise context.ContextNotFound("that conversation is not in the index")
    marks = hit_bookmarks.read_marks(state_dir, [conversation_id])
    return context.window(file, rules_mod.read_overrides(), marks, before=before, after=after, **anchor)


async def read(state_dir: Path, reader: Callable[[Callable[[sqlite3.Connection], Any]], Any], conversation_id: str, *,
               file_kind: str = K.FILE_CONVERSATION, line: Optional[int] = None, at: Optional[str] = None,
               before_line: Optional[int] = None, after_line: Optional[int] = None, before: int = context.WINDOW_DEFAULT,
               after: int = context.WINDOW_DEFAULT, host_key: Optional[str] = None, for_peer: bool = False) -> Dict[str, Any]:
    anchor = {"line": line, "at": at, "before_line": before_line, "after_line": after_line}
    if host_key and host_key != "local" and not for_peer:
        answer = await peer_deepsearch.context_from(state_dir, host_key, {
            "conversation_id": conversation_id, "file_kind": file_kind, "before": before, "after": after, **anchor})
        if answer.data is None:
            raise context.ContextNotFound("that conversation is not on that computer") if answer.reason == "http_404" \
                else PeerContextUnavailable(answer.reason)
        cleaned = await asyncio.to_thread(peer_deepsearch.clean_context, answer.data)
        if not cleaned:
            raise PeerContextUnavailable("bad_answer")
        return cleaned
    return await asyncio.to_thread(reader, lambda conn: _local(conn, state_dir, conversation_id, file_kind, for_peer, anchor, before, after))
