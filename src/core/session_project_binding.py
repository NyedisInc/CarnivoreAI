
from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.db_models import (
    PROJECT_SOURCE_ADOPTION,
    SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    SESSION_ATTRIBUTION_NONE,
    SESSION_ATTRIBUTION_UNKNOWN,
)
from src.core.project_attribution import attribute, normalize_path_for_match
from src.core.transcript_import_paths import canonical, git_top_level, is_scratch
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

BINDING_MATCHED = "matched"
BINDING_MATCHED_CANONICAL = "matched_canonical"
BINDING_CREATED = "created"
BINDING_FALLBACK_SYSOP = "fallback_sysop"
BINDING_NONE = "none"
BINDING_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProjectBinding:

    project_id: Optional[int] = None
    attribution: str = BINDING_UNKNOWN
    rule: str = BINDING_UNKNOWN
    created_project: bool = False
    root: Optional[str] = None
    detail: Optional[str] = None

    @property
    def determined(self) -> bool:
        return self.rule != BINDING_UNKNOWN


def matchable_roots(conn: sqlite3.Connection) -> Dict[str, int]:
    try:
        rows = conn.execute(
            "SELECT root, id FROM projects WHERE archived_at IS NULL"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(row[0]): int(row[1]) for row in rows}


def _spellings(working_dir: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    written = normalize_path_for_match(working_dir)
    if written is None:
        return None, None
    resolved = canonical(written)
    if not resolved or resolved == written:
        return written, None
    return written, resolved


def _chosen_dir(working_dir: str) -> str:
    return git_top_level(working_dir) or working_dir


def fold_path(path: str) -> str:
    return unicodedata.normalize("NFC", path).rstrip("/").casefold()


def swallows_live_root(root: str, live_roots: Dict[str, int]) -> bool:
    prefix = fold_path(root) + "/"
    return any(fold_path(live).startswith(prefix) for live in live_roots)


def _sysop_fallback_project(
    conn: sqlite3.Connection, working_dir: str, live_roots: Dict[str, int]
) -> Optional[int]:
    chosen = _chosen_dir(working_dir)
    root = canonical(chosen) or chosen
    spellings = {root, str(Path(chosen).expanduser())}
    swallows = swallows_live_root(root, live_roots)
    try:
        archived_here = any(
            conn.execute(
                "SELECT 1 FROM projects WHERE root = ? AND archived_at IS NOT NULL",
                (spelling,),
            ).fetchone()
            for spelling in spellings
        )
        if not (swallows or archived_here):
            return None
        from src.core.swarm import alpha

        agent = alpha.live_alpha(conn)
        sysop_project = agent.get("project_id") if agent else None
        if sysop_project is None:
            return None
        live = conn.execute(
            "SELECT 1 FROM projects WHERE id = ? AND archived_at IS NULL",
            (sysop_project,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning(
            "session_project_sysop_fallback_unreadable",
            working_dir=working_dir, error=str(exc),
        )
        return None
    return int(sysop_project) if live is not None else None


def ensure_project_row(
    conn: sqlite3.Connection,
    working_dir: str,
    *,
    now: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Tuple[Optional[int], bool, Optional[str]]:
    stamp = now or utc_now()
    chosen = _chosen_dir(working_dir)
    root = canonical(chosen) or chosen
    lookups = [root]
    written = str(Path(chosen).expanduser())
    if written != root:
        lookups.append(written)
    try:
        for candidate in lookups:
            found = conn.execute(
                "SELECT id FROM projects WHERE root = ?", (candidate,)
            ).fetchone()
            if found is not None:
                return int(found[0]), False, candidate
        cursor = conn.execute(
            "INSERT INTO projects (root, raw_path, display_name, source, "
            "presence, created_at, updated_at, last_opened_at) "
            "VALUES (?, ?, ?, ?, 'unchecked', ?, ?, ?)",
            (
                root,
                root,
                _display_name_for(root, conn, display_name),
                PROJECT_SOURCE_ADOPTION,
                stamp,
                stamp,
                stamp,
            ),
        )
    except sqlite3.Error as exc:
        logger.warning(
            "session_project_mint_failed",
            working_dir=working_dir,
            root=root,
            error=str(exc),
            note="the projects table could not be read or written",
        )
        return None, False, None
    return int(cursor.lastrowid), True, root


def _display_name_for(root: str, conn: sqlite3.Connection, preferred: Optional[str] = None) -> str:
    base = (preferred or "").strip() or Path(root).name or root
    candidate = base
    suffix = 2
    while True:
        try:
            taken = conn.execute(
                "SELECT 1 FROM projects WHERE display_name = ?", (candidate,)
            ).fetchone()
        except sqlite3.Error:
            return candidate
        if taken is None:
            return candidate
        candidate = f"{base} ({suffix})"
        suffix += 1


def resolve_project_binding(
    conn: sqlite3.Connection,
    working_dir: Optional[str],
    *,
    stored_project_id: Optional[int] = None,
    allow_create: bool = False,
    now: Optional[str] = None,
    roots: Optional[Dict[str, int]] = None,
    display_name: Optional[str] = None,
) -> ProjectBinding:
    known = matchable_roots(conn) if roots is None else roots
    written, resolved = _spellings(working_dir)

    if written is None:
        return ProjectBinding(
            project_id=stored_project_id,
            attribution=SESSION_ATTRIBUTION_UNKNOWN,
            rule=BINDING_UNKNOWN,
            detail="the working directory could not be read or situated",
        )

    matched_id, matched_attr = attribute(written, known)
    if matched_attr == SESSION_ATTRIBUTION_DERIVED_DEEPEST:
        return ProjectBinding(
            project_id=matched_id,
            attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
            rule=BINDING_MATCHED,
            root=written,
        )

    if resolved is not None:
        canon_id, canon_attr = attribute(resolved, known)
        if canon_attr == SESSION_ATTRIBUTION_DERIVED_DEEPEST:
            logger.info(
                "session_project_matched_canonical",
                working_dir=written,
                canonical_dir=resolved,
                project_id=canon_id,
                note=(
                    "the path as written matched no project root; it "
                    "matched once symlinks were resolved"
                ),
            )
            return ProjectBinding(
                project_id=canon_id,
                attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                rule=BINDING_MATCHED_CANONICAL,
                root=resolved,
            )

    if is_scratch(written):
        return ProjectBinding(
            project_id=stored_project_id,
            attribution=SESSION_ATTRIBUTION_NONE,
            rule=BINDING_NONE,
            detail="a per-run scratch directory can never be a project root",
        )

    if allow_create:
        sysop_project = _sysop_fallback_project(conn, written, known)
        if sysop_project is not None:
            logger.info(
                "session_project_fallback_sysop",
                working_dir=written,
                project_id=sysop_project,
                note=(
                    "no live project owns this folder and a project there "
                    "would be archived or would swallow live projects, so "
                    "the SysOp's project took the session"
                ),
            )
            return ProjectBinding(
                project_id=sysop_project,
                attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                rule=BINDING_FALLBACK_SYSOP,
                root=written,
            )
        project_id, created, root = ensure_project_row(conn, written, now=now, display_name=display_name)
        if project_id is not None:
            if created:
                logger.info(
                    "session_project_minted",
                    working_dir=written,
                    root=root,
                    project_id=project_id,
                    note=(
                        "no project contained this session's directory, so "
                        "one was created at it: every session belongs to a "
                        "project"
                    ),
                )
            return ProjectBinding(
                project_id=project_id,
                attribution=SESSION_ATTRIBUTION_DERIVED_DEEPEST,
                rule=BINDING_CREATED if created else BINDING_MATCHED,
                created_project=created,
                root=root,
            )
        return ProjectBinding(
            project_id=stored_project_id,
            attribution=SESSION_ATTRIBUTION_UNKNOWN,
            rule=BINDING_UNKNOWN,
            detail="a project could not be created for this directory",
        )

    return ProjectBinding(
        project_id=stored_project_id,
        attribution=SESSION_ATTRIBUTION_NONE,
        rule=BINDING_NONE,
        detail="no known project root contains this directory",
    )


def columns_to_write(
    binding: ProjectBinding, stored_project_id: Optional[int]
) -> Tuple[Optional[int], Optional[str]]:
    if binding.attribution == SESSION_ATTRIBUTION_DERIVED_DEEPEST \
            and binding.project_id is not None:
        return binding.project_id, SESSION_ATTRIBUTION_DERIVED_DEEPEST
    if binding.attribution == SESSION_ATTRIBUTION_NONE \
            and stored_project_id is None:
        return None, SESSION_ATTRIBUTION_NONE
    return None, None


def _derived_onto_ancestor(
    attribution: Optional[str], current_root: Optional[str], prefixes: set
) -> bool:
    if attribution != SESSION_ATTRIBUTION_DERIVED_DEEPEST or not current_root:
        return False
    held = {
        spelling.rstrip("/")
        for spelling in (normalize_path_for_match(current_root), canonical(current_root))
        if spelling
    }
    return any(prefix.startswith(root + "/") for prefix in prefixes for root in held)


def _memo_spellings(path: Optional[str], memo: Dict[str, frozenset]) -> frozenset:
    if not path:
        return frozenset()
    if path not in memo:
        memo[path] = frozenset(
            spelling.rstrip("/")
            for spelling in (normalize_path_for_match(path), canonical(path))
            if spelling
        )
    return memo[path]


def correct_shallow_derivations(
    conn: sqlite3.Connection, *, now: Optional[str] = None
) -> int:
    roots = matchable_roots(conn)
    if not roots:
        return 0
    try:
        rows = conn.execute(
            "SELECT s.id, s.working_dir, s.project_id, p.root FROM sessions s "
            "JOIN projects p ON p.id = s.project_id "
            "WHERE s.archived_at IS NULL AND s.working_dir IS NOT NULL AND s.project_attribution = ?",
            (SESSION_ATTRIBUTION_DERIVED_DEEPEST,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("project_backfill_unreadable", error=str(exc),
                       note="no session was re-attributed; nothing was written")
        return 0
    memo: Dict[str, frozenset] = {}
    root_prefixes = {pid: _memo_spellings(root, memo) for root, pid in roots.items()}
    stamp = now or utc_now()
    moved = 0
    for row_id, working_dir, current_pid, current_root in rows:
        held = _memo_spellings(current_root, memo)
        paths = _memo_spellings(working_dir, memo)
        best_pid, best_len = None, -1
        for pid, prefixes in root_prefixes.items():
            if pid == current_pid or not any(p.startswith(h + "/") for p in prefixes for h in held):
                continue
            under = [p for p in prefixes if any(c == p or c.startswith(p + "/") for c in paths)]
            if under and max(map(len, under)) > best_len:
                best_pid, best_len = pid, max(map(len, under))
        if best_pid is None:
            continue
        conn.execute(
            "UPDATE sessions SET project_id = ?, project_attribution = ?, updated_at = ? WHERE id = ?",
            (best_pid, SESSION_ATTRIBUTION_DERIVED_DEEPEST, stamp, int(row_id)),
        )
        moved += 1
    if moved:
        logger.info("project_backfill_adopted_sessions", sessions=moved,
                    note="sessions derived onto a shallower ancestor project were re-homed to the deepest match")
    return moved


def backfill_sessions_under_root(
    conn: sqlite3.Connection,
    *,
    root: str,
    project_id: int,
    now: Optional[str] = None,
    adopt_unassigned: bool = True,
    skip_ids: frozenset = frozenset(),
) -> int:
    return len(adopt_sessions_under_root(
        conn, root=root, project_id=project_id, now=now, adopt_unassigned=adopt_unassigned, skip_ids=skip_ids
    ))


def plan_adoptions(
    conn: sqlite3.Connection,
    *,
    root: str,
    project_id: int,
    adopt_unassigned: bool = True,
    skip_ids: frozenset = frozenset(),
) -> List[Dict[str, Any]]:
    prefixes = set()
    for spelling in (normalize_path_for_match(root), canonical(root)):
        if spelling:
            prefixes.add(spelling.rstrip("/"))
    if not prefixes:
        return []
    written: List[Dict[str, Any]] = []
    try:
        rows = conn.execute(
            "SELECT s.id, s.working_dir, s.project_id, "
            "s.project_attribution, p.root FROM sessions s "
            "LEFT JOIN projects p ON p.id = s.project_id "
            "WHERE s.archived_at IS NULL AND s.working_dir IS NOT NULL "
            "AND s.project_id IS NOT ?"
        , (project_id,)).fetchall()
    except sqlite3.Error as exc:
        logger.warning(
            "project_backfill_unreadable",
            root=root,
            error=str(exc),
            note="no session was re-attributed; nothing was written",
        )
        return []
    for row in rows:
        if int(row[0]) in skip_ids:
            continue
        if row[2] is None:
            if not adopt_unassigned:
                continue
        elif not _derived_onto_ancestor(row[3], row[4], prefixes):
            continue
        candidates = {
            spelling
            for spelling in (
                normalize_path_for_match(row[1]),
                canonical(row[1]),
            )
            if spelling
        }
        if not any(
            candidate == prefix or candidate.startswith(prefix + "/")
            for candidate in candidates
            for prefix in prefixes
        ):
            continue
        written.append({"id": int(row[0]), "from_project_id": row[2], "from_attribution": row[3]})
    return written


def adopt_sessions_under_root(
    conn: sqlite3.Connection,
    *,
    root: str,
    project_id: int,
    now: Optional[str] = None,
    adopt_unassigned: bool = True,
    skip_ids: frozenset = frozenset(),
) -> List[Dict[str, Any]]:
    stamp = now or utc_now()
    moved = plan_adoptions(conn, root=root, project_id=project_id, adopt_unassigned=adopt_unassigned, skip_ids=skip_ids)
    for entry in moved:
        conn.execute(
            "UPDATE sessions SET project_id = ?, project_attribution = ?, updated_at = ? WHERE id = ?",
            (project_id, SESSION_ATTRIBUTION_DERIVED_DEEPEST, stamp, entry["id"]),
        )
    if moved:
        logger.info(
            "project_backfill_adopted_sessions",
            root=root,
            project_id=project_id,
            sessions=len(moved),
            note=(
                "sessions that had no project, or were derived onto a "
                "shallower ancestor project, and sit under this root"
            ),
        )
    return moved
