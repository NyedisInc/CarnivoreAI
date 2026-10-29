
from __future__ import annotations

import sqlite3
from typing import Dict, List, Sequence

import structlog

from src.config.launch_profiles import LaunchProfile
from src.core import blueprints_store
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

KINDS = ("sessions", "blueprint_members", "project_defaults")


class UsageUnknown(RuntimeError):
    """A reference kind could not be read, so "unreferenced" cannot be claimed. The message names the kind."""


def count_references(conn: sqlite3.Connection, profile_id: str) -> Dict[str, int]:
    sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE agent_type = ?", (profile_id,)).fetchone()[0]
    projects = conn.execute("SELECT COUNT(*) FROM projects WHERE default_agent_type = ?", (profile_id,)).fetchone()[0]
    try:
        members = sum(1 for bp in blueprints_store.list_blueprints(conn) for s in bp.spec.sessions if s.family == profile_id)
    except blueprints_store.BlueprintError as exc:
        raise UsageUnknown(f"blueprints could not be read: {exc}") from exc
    return {"sessions": int(sessions), "blueprint_members": members, "project_defaults": int(projects)}


def move_references(conn: sqlite3.Connection, from_id: str, to_id: str) -> Dict[str, int]:
    moved = {kind: 0 for kind in KINDS}
    with conn:
        moved["sessions"] = conn.execute("UPDATE sessions SET agent_type = ? WHERE agent_type = ?", (to_id, from_id)).rowcount
        moved["project_defaults"] = conn.execute(
            "UPDATE projects SET default_agent_type = ? WHERE default_agent_type = ?", (to_id, from_id)).rowcount
    try:
        for saved in blueprints_store.list_blueprints(conn):
            hits = [s for s in saved.spec.sessions if s.family == from_id]
            if not hits:
                continue
            spec = saved.spec.model_copy(deep=True)
            for member in spec.sessions:
                if member.family == from_id:
                    member.family = to_id
            blueprints_store.replace_blueprint(conn, saved.blueprint_uuid, spec, now=utc_now())
            moved["blueprint_members"] += len(hits)
    except blueprints_store.BlueprintError as exc:
        raise UsageUnknown(f"blueprints could not be moved: {exc}") from exc
    logger.info("launch_profile_references_moved", from_id=from_id, to_id=to_id, **moved)
    return moved


def profiles_using_connection(profiles: Sequence[LaunchProfile], connection_id: str) -> List[LaunchProfile]:
    return [p for p in profiles if p.endpoint.mode == "connection" and p.endpoint.connection_id == connection_id]
