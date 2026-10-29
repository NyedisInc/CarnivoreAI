
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, Set

import structlog

from src.core.db import connect, table_exists
from src.core.swarm.leaders import LEADER_RANKS

logger = structlog.get_logger()

PENDING_STATUSES = ("queued", "held", "delivering")


@dataclass(frozen=True)
class Member:

    agent_id: int
    row_id: int
    session_uuid: str
    tmux_name: str
    rank: str = ""

    @property
    def is_leader(self) -> bool:
        return self.rank in LEADER_RANKS


@dataclass
class Members:

    by_row: Dict[int, Member] = field(default_factory=dict)
    busy_keys: Set[str] = field(default_factory=set)
    parents_with_children: Set[int] = field(default_factory=set)
    parents_with_reports: Set[int] = field(default_factory=set)
    askers_routing: Set[int] = field(default_factory=set)


def read_members(db_path: Path) -> Members:
    members = Members()
    if not Path(db_path).exists():
        return members
    with closing(connect(db_path, create=False)) as conn:
        if not table_exists(conn, "swarm_agents"):
            return members
        for r in conn.execute(
                "SELECT a.id, a.session_row_id, s.session_uuid, s.tmux_name, a.rank FROM swarm_agents a "
                "JOIN sessions s ON s.id = a.session_row_id WHERE a.torn_down_at IS NULL"):
            members.by_row[int(r[1])] = Member(int(r[0]), int(r[1]), str(r[2]), str(r[3] or ""), str(r[4]))
        members.parents_with_children = {int(r[0]) for r in conn.execute(
            "SELECT DISTINCT a.parent_id FROM swarm_wakes w JOIN swarm_agents a ON a.id = w.agent_id "
            "WHERE w.ended_at IS NULL AND a.parent_id IS NOT NULL")}
        if table_exists(conn, "swarm_reports"):
            members.parents_with_reports = {int(r[0]) for r in conn.execute("SELECT DISTINCT parent_id FROM swarm_reports WHERE state = 'pending'")}
        if table_exists(conn, "swarm_questions"):
            members.askers_routing = {int(r[0]) for r in conn.execute(
                "SELECT DISTINCT k.agent_id FROM swarm_question_askers k JOIN swarm_questions q ON q.id = k.question_id "
                "WHERE q.state IN ('routing', 'reopened')")}
        if table_exists(conn, "crosstalk_messages"):
            marks = ",".join("?" for _ in PENDING_STATUSES)
            for r in conn.execute(f"SELECT sender_key, receiver_key FROM crosstalk_messages WHERE status IN ({marks})",
                                  PENDING_STATUSES):
                members.busy_keys.update((str(r[0]), str(r[1])))
    return members


def pending_reason(member: Member, members: Members) -> Optional[str]:
    from src.core.mcp import pending

    if member.session_uuid in members.busy_keys:
        return "crosstalk traffic is queued, held or being delivered"
    if member.agent_id in members.parents_with_children:
        return "a child agent's body is live"
    if member.agent_id in members.parents_with_reports:
        return "a child's report is waiting to be accepted"
    if member.agent_id in members.askers_routing:
        return "a question it asked is still routing"
    if any(row.get("caller_tmux") == member.tmux_name for row in pending.get_store().list()):
        return "an approval from its body is parked"
    return None


async def sleep_agent(app_state: Any, agent_id: int) -> Any:
    from src.core.swarm import body

    try:
        result = await body.sleep(app_state, agent_id, "auto_sleep")
    except body.BodyError as exc:
        logger.info("swarm_auto_sleep_refused", agent_id=agent_id, error=str(exc)[:200])
        return SimpleNamespace(status="refused", code="swarm_sleep", session_name=None)
    return SimpleNamespace(status=result.state, code=None, session_name=None)
