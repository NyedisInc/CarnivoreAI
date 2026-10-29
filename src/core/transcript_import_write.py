
from __future__ import annotations

import os
import sqlite3
import uuid as _uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import structlog

from src.core.transcript_import_plan import (
    IMPORTED_PROJECT_SOURCE,
    IMPORTED_ROW_CONSTANTS,
    ProposedSession,
)
from src.core.session_kind import classify_transcript
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

WROTE_SESSION = "wrote"

SKIPPED_HELD = "skipped_held"

DISPLAY_NAME_MAX_SEGMENTS = 3


@dataclass(frozen=True)
class ImportReport:

    sessions_written: int = 0
    sessions_skipped_held: int = 0
    projects_created: int = 0
    projects_reused: int = 0


def display_name_for(
    root: str, taken: Sequence[str], *, max_segments: int = DISPLAY_NAME_MAX_SEGMENTS
) -> str:
    used = set(taken)
    parts = [p for p in root.split(os.sep) if p]
    if not parts:
        return root
    for width in range(1, min(max_segments, len(parts)) + 1):
        candidate = os.sep.join(parts[-width:])
        if candidate not in used:
            return candidate
    return root if root not in used else f"{root} ({_uuid.uuid4().hex[:6]})"


def _existing_project_ids(conn: sqlite3.Connection) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in conn.execute("SELECT id, root FROM projects"):
        try:
            key = os.path.realpath(str(row[1]))
        except OSError:
            key = str(row[1])
        out.setdefault(key, int(row[0]))
    return out


def _display_names(conn: sqlite3.Connection) -> List[str]:
    return [str(r[0]) for r in conn.execute("SELECT display_name FROM projects")]


def _held_uuids(conn: sqlite3.Connection) -> set:
    return {
        str(r[0])
        for r in conn.execute(
            "SELECT claude_session_uuid FROM sessions "
            "WHERE claude_session_uuid IS NOT NULL"
        )
    }


def create_archived_project(
    conn: sqlite3.Connection,
    root: str,
    *,
    display_name: str,
    now: str,
) -> int:
    cursor = conn.execute(
        "INSERT INTO projects "
        "(root, raw_path, display_name, source, archived_at, "
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (root, root, display_name, IMPORTED_PROJECT_SOURCE, now, now, now),
    )
    return int(cursor.lastrowid)



def kind_for_plan(plan: ProposedSession) -> Optional[str]:
    if not plan.transcript_path:
        return None
    return classify_transcript(plan.transcript_path).kind


MEASURE_KIND: Any = object()


def insert_imported_session(
    conn: sqlite3.Connection,
    plan: ProposedSession,
    *,
    project_id: int,
    now: str,
    kind: Optional[str] = MEASURE_KIND,
) -> str:
    session_uuid = str(_uuid.uuid4())
    stamp = plan.created_at or now
    if kind is MEASURE_KIND:
        kind = kind_for_plan(plan)
    conn.execute(
        "INSERT INTO sessions "
        "(session_uuid, project_id, project_attribution, working_dir, "
        " origin, lifecycle, lifecycle_source, lifecycle_checked_at, "
        " claude_session_uuid, claude_session_uuid_source, title, "
        " archived_at, created_at, updated_at, last_work_at, kind) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_uuid,
            project_id,
            IMPORTED_ROW_CONSTANTS["project_attribution"],
            plan.working_dir,
            IMPORTED_ROW_CONSTANTS["origin"],
            IMPORTED_ROW_CONSTANTS["lifecycle"],
            IMPORTED_ROW_CONSTANTS["lifecycle_source"],
            now,
            plan.claude_session_uuid,
            IMPORTED_ROW_CONSTANTS["claude_session_uuid_source"],
            plan.title,
            now,
            stamp,
            now,
            plan.last_work_at,
            kind,
        ),
    )
    return session_uuid


def apply_plans(
    conn: sqlite3.Connection,
    plans: Sequence[ProposedSession],
    *,
    now: Optional[str] = None,
) -> ImportReport:
    stamp = now or utc_now()
    writable = [p for p in plans if p.writes]
    report = ImportReport()
    if not writable:
        return report

    measured = [(plan, kind_for_plan(plan)) for plan in writable]
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        held = _held_uuids(conn)
        project_ids = _existing_project_ids(conn)
        names = _display_names(conn)
        created = 0
        reused = 0
        written = 0
        skipped = 0
        for plan, kind in measured:
            if plan.claude_session_uuid in held:
                skipped += 1
                continue
            root = plan.project_root
            project_id = project_ids.get(root)
            if project_id is None:
                name = display_name_for(root, names)
                project_id = create_archived_project(
                    conn, root, display_name=name, now=stamp
                )
                project_ids[root] = project_id
                names.append(name)
                created += 1
            else:
                reused += 1
            insert_imported_session(
                conn, plan, project_id=project_id, now=stamp, kind=kind
            )
            held.add(plan.claude_session_uuid)
            written += 1
        report = ImportReport(
            sessions_written=written,
            sessions_skipped_held=skipped,
            projects_created=created,
            projects_reused=reused,
        )
    logger.info(
        "transcript_sessions_imported",
        sessions_written=report.sessions_written,
        sessions_skipped_held=report.sessions_skipped_held,
        projects_created=report.projects_created,
        projects_reused=report.projects_reused,
    )
    return report
