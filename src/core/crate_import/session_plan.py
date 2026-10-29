
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.core.crate_import.keyrules import REF, rule_for
from src.core.crate_import.model import W_SESSION_REMINTED, Collector

REMINT_NAMESPACE = uuid.UUID("6c0f2b86-3b5e-4f1a-9a52-7a4d6f0a9c11")
SKIPPED_BY_CONVERSATION = "conversation_not_restored"

CONVERSATION_KEY_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "conversation_index": ("conversation_id",),
    "conversation_milestones": ("conversation_id",),
    "session_conversations": ("conversation_id", "parent_conversation_id"),
    "lineage_nodes": ("node_id",),
    "lineage_edges": ("parent_id", "child_id"),
    "agent_spawn_links": ("child_id", "parent_id"),
    "bookmarks": ("claude_session_uuid",),
    "messaging_messages": ("conversation_id",),
}


def reminted_uuid(bundle_id: str, old: str) -> str:
    return str(uuid.uuid5(REMINT_NAMESPACE, f"{bundle_id}:{old}"))


@dataclass(frozen=True)
class SessionPlan:

    skip_sessions: FrozenSet[str] = frozenset()
    skip_conversations: FrozenSet[str] = frozenset()
    translate: Mapping[str, str] = field(default_factory=dict)
    reminted: Tuple[str, ...] = ()

    def translate_row(self, store: str, table: str, row: Dict[str, Any]) -> None:
        for column, value in list(row.items()):
            if isinstance(value, str) and value in self.translate and self._names_session(store, table, column):
                row[column] = self.translate[value]

    def skip_reason(self, store: str, table: str, row: Mapping[str, Any]) -> Optional[str]:
        for column, value in row.items():
            if isinstance(value, str) and value in self.skip_sessions and self._names_session(store, table, column):
                return SKIPPED_BY_CONVERSATION
        for column in CONVERSATION_KEY_COLUMNS.get(table, ()):
            if row.get(column) in self.skip_conversations:
                return SKIPPED_BY_CONVERSATION
        return None

    @staticmethod
    def _names_session(store: str, table: str, column: str) -> bool:
        if table == "sessions" and column == "session_uuid":
            return True
        rule = rule_for(store, table, column)
        return rule is not None and rule.kind == REF and rule.target == "sessions.session_uuid"


def held_by(conn: sqlite3.Connection, crate_sessions: Sequence[Tuple[str, Optional[str]]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for session_uuid, conversation in crate_sessions:
        if not conversation:
            continue
        row = conn.execute("SELECT session_uuid FROM sessions WHERE claude_session_uuid = ? AND session_uuid != ? LIMIT 1",
                           (conversation, session_uuid)).fetchone()
        if row is not None:
            out[conversation] = row["session_uuid"]
    return out


def plan_sessions(conn: sqlite3.Connection, raw_rows: Iterable[Mapping[str, Any]], excluded: FrozenSet[str], bundle_id: str,
                  col: Collector) -> SessionPlan:
    rows = [r for r in raw_rows if r.get("session_uuid")]
    holders = held_by(conn, [(str(r["session_uuid"]), r.get("claude_session_uuid")) for r in rows])
    skip, translate, reminted = set(), {}, []
    for row in rows:
        old, conversation = str(row["session_uuid"]), row.get("claude_session_uuid")
        if conversation in excluded:
            skip.add(old)
            continue
        if conversation in holders:
            translate[old] = holders[conversation]
            continue
        here = conn.execute("SELECT claude_session_uuid FROM sessions WHERE session_uuid = ?", (old,)).fetchone()
        if here is not None and here["claude_session_uuid"] != conversation:
            translate[old] = reminted_uuid(bundle_id, old)
            reminted.append(old)
            col.warn(W_SESSION_REMINTED, old)
    return SessionPlan(frozenset(skip), frozenset(excluded), translate, tuple(reminted))
