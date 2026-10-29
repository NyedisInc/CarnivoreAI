
from __future__ import annotations

import sqlite3
from typing import List, Optional

import structlog

from src.core.inventory import entry_claims, file_claims, file_trace, identity, side_trace
from src.core.inventory import db_trace, registry
from src.core.inventory.claim_rows import trace_claims
from src.core.inventory.locations import Locations
from src.core.inventory.model import MAIN_STORE, SCOPE_PROJECT, SCOPE_SESSION, Inventory, ProjectIdentity, ProjectNotFound, SessionIdentity
from src.core.inventory.scope import CONVERSATIONS, project_scope, session_scope
from src.core.inventory.target import resolve_project_id, resolve_session_uuid

logger = structlog.get_logger()


def resolve_session(conn: sqlite3.Connection, session_uuid: str, locations: Locations, *,
                    related_blockers: Optional[List[str]] = None) -> Inventory:
    ident = identity.load_identity(conn, session_uuid)
    shared = identity.shared_with(conn, ident)
    shared_reason = "the conversation is shared with session " + ", ".join(s["name"] for s in shared) if shared else ""
    scope = session_scope(conn, ident)
    conversations = scope.values(CONVERSATIONS)
    db_arts, db_blockers = db_trace.trace(conn, ident, shared, identity.other_rows_named(conn, ident), scope)
    side_arts, side_blockers = side_trace.trace(locations.state_dir, locations.config_path, ident, shared_reason,
                                                locations.pinned_themes(), scope)
    file_arts, file_blockers = file_trace.trace(ident, shared_reason, homes=locations.homes, codex=locations.codex,
                                                related=[c for c in conversations if c != ident.conversation],
                                                related_blockers=related_blockers)
    more_files, more_blockers = file_claims.session_files(conn, scope, ident, locations)
    return Inventory(scope=SCOPE_SESSION, session=ident,
                     artifacts=db_arts + side_arts + file_arts + entry_claims.session_entries(ident, locations) + more_files,
                     blockers=db_blockers + side_blockers + file_blockers + more_blockers, shared_with=shared,
                     conversations=conversations, home_project=_home_project(conn, ident))


def _home_project(conn: sqlite3.Connection, ident: SessionIdentity) -> Optional[ProjectIdentity]:
    if ident.project_id is None:
        return None
    try:
        return identity.load_project(conn, ident.project_id)
    except ProjectNotFound:
        return None


def _outside_references(conn: sqlite3.Connection, project_id: int) -> List[str]:
    """Sentences for sessions OUTSIDE the project that were forked or resumed from one of its sessions. Output: list[str]."""
    sql = ("SELECT c.session_uuid, c.project_id, p.session_uuid FROM sessions c JOIN sessions p ON c.parent_session_id = p.id "
           "WHERE p.project_id = ? AND COALESCE(c.project_id, -1) != ? ORDER BY c.id")
    return [f"session {child} (project {other if other is not None else 'none'}) was forked or resumed from session {parent} "
            "of this project" for child, other, parent in conn.execute(sql, (project_id, project_id))]


def resolve_project(conn: sqlite3.Connection, project_id: int, locations: Locations, *,
                    related_blockers: Optional[List[str]] = None) -> Inventory:
    project = identity.load_project(conn, project_id)
    scope = project_scope(project)
    children = [resolve_session(conn, uuid, locations, related_blockers=related_blockers)
                for uuid in identity.project_session_uuids(conn, project_id)]
    claimed = [c for child in children for c in child.conversations]
    file_arts, file_blockers = file_claims.project_files(conn, scope, project, locations, claimed)
    arts = (trace_claims(registry.book(), scope, MAIN_STORE, conn) + side_trace.claimed_side_rows(locations.state_dir, scope)
            + entry_claims.project_entries(project, locations) + entry_claims.project_preference_entries(project, locations) + file_arts)
    return Inventory(scope=SCOPE_PROJECT, project=project, artifacts=arts, blockers=file_blockers, children=children,
                     outside=_outside_references(conn, project_id))


def resolve_session_target(conn: sqlite3.Connection, target: str, locations: Locations, *,
                           related_blockers: Optional[List[str]] = None) -> Inventory:
    """:func:`resolve_session` for a session row id (``row:12``), app id (``ses_...``), uuid, conversation id or tmux name.

    Raises: TargetNotFound; TargetAmbiguous (see ``target.py``).
    Example: resolve_session_target(conn, "ses_49759e95", locations)
    """
    return resolve_session(conn, resolve_session_uuid(conn, target), locations, related_blockers=related_blockers)


def resolve_project_target(conn: sqlite3.Connection, target: str, locations: Locations, *,
                           related_blockers: Optional[List[str]] = None) -> Inventory:
    return resolve_project(conn, resolve_project_id(conn, target), locations, related_blockers=related_blockers)
