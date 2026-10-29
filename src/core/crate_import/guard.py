"""Never touch a live session (section 9): the measurements an import repeats at plan time and again inside the apply.

READ ONLY. An unanswered measurement BLOCKS (not having looked is not a yes):

- ``panes_unknown``: the pane listing did not answer;
- ``session_live``: a crate session's uuid, or a local row holding the same conversation, has a live pane;
- ``conversation_live`` / ``writers_unmeasured``: a live claude process has a crate conversation open (any process, in tmux or
  not), or the process table could not be read;
- ``offer_names_session``: the open reopen offer names a crate session;
- the live row ids, so the new project row never adopts or re-parents a running session.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from src.core import session_journal_store as journal_store
from src.core.conversation_writers import writer_conflict
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import (
    B_CONVERSATION_LIVE, B_JOURNAL_UNREADABLE, B_OFFER_NAMES_SESSION, B_PANES_UNKNOWN, B_SESSION_LIVE, B_WRITERS_UNMEASURED,
    Collector,
)
from src.core.inventory.identity import load_identity
from src.core.inventory.model import SessionNotFound
from src.core.session_purge.identity import live_blocker


@dataclass
class LiveFacts:

    live_row_ids: FrozenSet[int] = frozenset()
    live_conversations: FrozenSet[str] = frozenset()
    live_sessions: FrozenSet[str] = frozenset()
    writer_pids: Tuple[int, ...] = ()
    notes: Dict[str, str] = field(default_factory=dict)


def local_live_row_ids(conn: sqlite3.Connection, panes: Sequence[Tuple[object, object, object]]) -> FrozenSet[int]:
    by_name: Dict[str, List[Optional[int]]] = {}
    for name, epoch, _path in panes:
        by_name.setdefault(str(name), []).append(int(epoch) if epoch is not None else None)
    live = set()
    for row in conn.execute("SELECT id, tmux_name, tmux_created_epoch FROM sessions WHERE tmux_name IS NOT NULL"):
        for epoch in by_name.get(str(row["tmux_name"]), ()):
            if epoch is None or row["tmux_created_epoch"] is None or epoch == int(row["tmux_created_epoch"]):
                live.add(int(row["id"]))
    return frozenset(live)


def _local_rows_for(conn: sqlite3.Connection, session_uuid: Optional[str], conversation: Optional[str]) -> List[str]:
    found: List[str] = []
    for column, value in (("session_uuid", session_uuid), ("claude_session_uuid", conversation)):
        if value:
            found += [r[0] for r in conn.execute(f"SELECT session_uuid FROM sessions WHERE {column} = ?", (value,))]
    return list(dict.fromkeys(found))


def _offer_names(env: ImportEnv, uuids: Iterable[str], col: Collector) -> None:
    loaded = journal_store.load_journal(env.state)
    if loaded.outcome == journal_store.LOAD_ABSENT:
        return
    if loaded.outcome != journal_store.LOAD_OK:
        col.block(B_JOURNAL_UNREADABLE, loaded.detail[:120])
        return
    offer = loaded.journal.get("offer")
    if offer:
        text = json.dumps(offer)
        for uuid in uuids:
            if uuid and uuid in text:
                col.block(B_OFFER_NAMES_SESSION, uuid)


def measure(env: ImportEnv, conn: sqlite3.Connection, crate_sessions: Sequence[Tuple[str, Optional[str]]],
            conversation_ids: Sequence[str], resume_dir: Optional[str], col: Collector) -> LiveFacts:
    panes = env.panes()
    facts = LiveFacts()
    if not panes.ok:
        col.block(B_PANES_UNKNOWN, panes.reason)
    else:
        facts = LiveFacts(live_row_ids=local_live_row_ids(conn, panes.panes))
        live_sessions: List[str] = []
        for session_uuid, conversation in crate_sessions:
            for local_uuid in _local_rows_for(conn, session_uuid, conversation):
                try:
                    ident = load_identity(conn, local_uuid)
                except SessionNotFound:
                    continue
                if live_blocker(ident, True, panes.panes) is not None:
                    live_sessions.append(local_uuid)
                    col.block(B_SESSION_LIVE, local_uuid)
        facts.live_sessions = frozenset(live_sessions)
    writers = env.writers()
    if writers is None:
        col.block(B_WRITERS_UNMEASURED, "ps")
    else:
        live: List[str] = []
        cwd = os.path.realpath(resume_dir) if resume_dir else None
        for conversation in conversation_ids:
            hit = writer_conflict(conversation, cwd, writers)
            if hit is not None:
                live.append(conversation)
                col.block(B_CONVERSATION_LIVE, f"{conversation}: {hit[0]}")
        facts.live_conversations = frozenset(live)
        facts.writer_pids = tuple(sorted(w.pid for w in writers))
    _offer_names(env, [u for u, _c in crate_sessions], col)
    return facts
