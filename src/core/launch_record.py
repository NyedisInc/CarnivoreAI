
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

import structlog

from src.core.agent_families import resolve_agent_type, wrappers_for_family
from src.core.agent_wrappers import default_wrapper

if TYPE_CHECKING:
    from src.core.launch_profiles.plan import LaunchPlan

logger = structlog.get_logger()


@dataclass(frozen=True)
class LaunchRecord:

    family: str
    agent_type: str


def _wrapper_id(wrapper: object) -> Optional[str]:
    wid = wrapper.get("id") if isinstance(wrapper, dict) else getattr(wrapper, "id", None)
    return str(wid) if wid else None


def launch_record(agent_type: Optional[str], wrappers: List) -> LaunchRecord:
    family, explicit = resolve_agent_type(agent_type, wrappers)
    chosen = explicit if explicit is not None else default_wrapper(
        wrappers_for_family(wrappers, family.name)
    )
    wid = _wrapper_id(chosen) if chosen is not None else None
    return LaunchRecord(family=family.name, agent_type=wid or family.name)


def record_launch_on_row(
    conn: sqlite3.Connection,
    *,
    row_id: int,
    agent_type: Optional[str],
    agent_family: Optional[str],
    family_source: Optional[str],
) -> bool:
    if family_source is None:
        return False
    cursor = conn.execute(
        "UPDATE sessions SET agent_type = ?, agent_family = ?, "
        "agent_family_source = ? WHERE id = ?",
        (agent_type, agent_family, family_source, int(row_id)),
    )
    written = int(cursor.rowcount or 0) > 0
    logger.info(
        "launch_recorded_on_reused_row",
        session_id=int(row_id),
        agent_type=agent_type,
        agent_family=agent_family,
        agent_family_source=family_source,
        written=written,
    )
    return written


def launch_record_json(plan: "LaunchPlan", account_id: Optional[str]) -> str:
    display = plan.display
    endpoint = {"connection_id": plan.connection_id, "label": display.endpoint} if plan.connection_id else None
    return json.dumps({
        "profile": plan.profile_id, "digest": plan.digest, "harness": display.harness,
        "account": {"mode": plan.account_mode, "id": account_id},
        "endpoint": endpoint, "model": display.model, "permissions": display.permissions,
        "purpose": plan.purpose,
    }, sort_keys=True, separators=(",", ":"))


def write_launch_record(conn: sqlite3.Connection, *, session_uuid: Optional[str], record: Optional[str]) -> bool:
    if not record or not session_uuid:
        return False
    cursor = conn.execute("UPDATE sessions SET launch_record = ? WHERE session_uuid = ?", (record, session_uuid))
    return int(cursor.rowcount or 0) > 0
