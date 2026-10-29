
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

import structlog

from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope
from src.core.session_agent_provenance import (
    DEFINITE_LAUNCH_SOURCES,
    NOT_KNOWN,
    StoredLaunch,
)
from src.core.session_label import _clean_title

logger = structlog.get_logger()

InstanceKey = Tuple[str, int]


@dataclass(frozen=True)
class InstanceFacts:

    title: Optional[str] = None
    row_id: Optional[int] = None
    parent_session_id: Optional[Any] = None
    agent_type: Optional[str] = None
    agent_family_source: Optional[str] = None
    agent_family: Optional[str] = None
    activity_state: Optional[str] = None
    activity_state_at: Optional[Any] = None
    claude_session_uuid: Optional[str] = None
    working_dir: Optional[str] = None


class InstanceIndex:

    def __init__(
        self,
        facts: Optional[Dict[InstanceKey, InstanceFacts]] = None,
        *,
        complete: bool = False,
    ):
        self._facts: Dict[InstanceKey, InstanceFacts] = dict(facts or {})
        self.complete: bool = bool(complete)

    def _get(self, name: Optional[str], epoch: Optional[int]) -> Optional[InstanceFacts]:
        if not name or epoch is None:
            return None
        try:
            return self._facts.get((name, int(epoch)))
        except (TypeError, ValueError):
            return None

    def label(self, name: Optional[str], epoch: Optional[int]) -> Optional[str]:
        facts = self._get(name, epoch)
        return facts.title if facts else None

    def identity(
        self, name: Optional[str], epoch: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        facts = self._get(name, epoch)
        if facts is None:
            return None
        return {
            "id": facts.row_id,
            "parent_session_id": facts.parent_session_id,
            "agent_type": facts.agent_type,
            "claude_session_uuid": facts.claude_session_uuid or None,
        }

    def row_identity(
        self, name: Optional[str], epoch: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        facts = self._get(name, epoch)
        if facts is None or facts.row_id is None:
            return None
        return {
            "id": int(facts.row_id),
            "parent_session_id": facts.parent_session_id,
            "agent_type": facts.agent_type,
            "agent_family": facts.agent_family,
            "agent_family_source": facts.agent_family_source,
        }

    def stored_launch(
        self, name: Optional[str], epoch: Optional[int]
    ) -> StoredLaunch:
        facts = self._get(name, epoch)
        if facts is None:
            return NOT_KNOWN
        if facts.agent_family_source not in DEFINITE_LAUNCH_SOURCES:
            return NOT_KNOWN
        return StoredLaunch(
            known=True, agent_type=facts.agent_type, from_fingerprint=False
        )

    def seed_row(
        self, name: Optional[str], epoch: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        facts = self._get(name, epoch)
        if facts is None:
            return None
        return {
            "activity_state": facts.activity_state,
            "activity_state_at": facts.activity_state_at,
            "claude_session_uuid": facts.claude_session_uuid,
            "working_dir": facts.working_dir,
        }


def build_instance_index(
    conn, *, socket: str, names: Iterable[str], host_key: str = LOCAL_HOST_KEY
) -> InstanceIndex:
    wanted = [n for n in dict.fromkeys(names) if n]
    if conn is None or not socket:
        return InstanceIndex()
    if not wanted:
        return InstanceIndex(complete=True)

    chunk_size = 400
    facts: Dict[InstanceKey, InstanceFacts] = {}
    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        for start in range(0, len(wanted), chunk_size):
            chunk = wanted[start:start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                "SELECT id, parent_session_id, agent_type, agent_family, "
                "agent_family_source, title, tmux_name, tmux_created_epoch, "
                "activity_state, activity_state_at, claude_session_uuid, "
                "working_dir "
                "FROM sessions "
                f"WHERE tmux_socket = ? AND tmux_name IN ({placeholders}) "
                f"AND tmux_created_epoch IS NOT NULL{scope_sql} "
                "ORDER BY id ASC",
                (socket, *chunk, *scope_params),
            ).fetchall()
            for raw in rows:
                row = dict(raw)
                try:
                    key: InstanceKey = (
                        row["tmux_name"], int(row["tmux_created_epoch"])
                    )
                except (TypeError, ValueError, KeyError):
                    continue
                title = _clean_title(row.get("title"))
                existing = facts.get(key)
                if existing is None:
                    facts[key] = InstanceFacts(
                        title=title,
                        row_id=row.get("id"),
                        parent_session_id=row.get("parent_session_id"),
                        agent_type=row.get("agent_type"),
                        agent_family_source=row.get("agent_family_source"),
                        agent_family=row.get("agent_family"),
                        activity_state=row.get("activity_state"),
                        activity_state_at=row.get("activity_state_at"),
                        claude_session_uuid=row.get("claude_session_uuid"),
                        working_dir=row.get("working_dir"),
                    )
                else:
                    facts[key] = InstanceFacts(
                        title=title,
                        row_id=existing.row_id,
                        parent_session_id=existing.parent_session_id,
                        agent_type=existing.agent_type,
                        agent_family_source=existing.agent_family_source,
                        agent_family=existing.agent_family,
                        activity_state=existing.activity_state,
                        activity_state_at=existing.activity_state_at,
                        claude_session_uuid=existing.claude_session_uuid,
                        working_dir=existing.working_dir,
                    )
    except (sqlite3.Error, TypeError, ValueError) as exc:
        logger.warning(
            "instance_index_read_failed",
            tmux_socket=socket,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return InstanceIndex()
    return InstanceIndex(facts, complete=True)
