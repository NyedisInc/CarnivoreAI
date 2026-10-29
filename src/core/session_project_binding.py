"""Giving every live session a project, and never writing half an answer.

The rule this module adds: THE PAIR MOVES TOGETHER OR NEITHER MOVES.
A derivation that cannot beat what the row already holds writes nothing
at all.

So the ladder gets a SECOND rung: try the path as written, and only if
that matches nothing, try it canonicalised. Canonicalising is a
FALLBACK, never the primary comparison - the as-written match still wins
- so a project declared at a symlink keeps collecting the sessions
declared at that same symlink. ``transcript_import_paths.canonical`` is
the spelling function, imported rather than re-implemented, because this
codebase already decided realpath is "the one spelling this codebase
stores for a directory".

THREE OUTCOMES SURVIVE, AND THE FOURTH IS NEW.

  ``matched``            the directory as written sits under a project.
  ``matched_canonical``  it does once the symlinks are resolved. Same
                         attribution value on the row; a separate rule
                         name so a reader can tell which rung fired,
                         because a rung nobody has ever observed to fire
                         is unmeasured rather than proven.
  ``created``            it sits under nothing, so a project was minted
                         at it. Only ever with ``allow_create=True``.
  ``none``               read, and deliberately not given a project: the
                         one exclusion is a per-run scratch directory,
                         which can never be a project root.
  ``unknown``            could not be read or situated. NOT an answer,
                         and it writes nothing, ever.

WHY SCRATCH IS THE ONLY EXCLUSION. It is the same single exclusion the
transcript importer names, and it is about the PATH, not about the work:
``/private/tmp``, ``/tmp`` and ``/var/folders`` hold per-run directories
that are gone by tomorrow, and minting a project at one would put a dead
folder in the launcher forever.
"""

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
    """A path spelled for case-insensitive comparison (the safety guards only, never for storage or lookup).

    Description: macOS volumes are case-insensitive by default (APFS) yet ``os.path.realpath`` keeps the spelling it
      was given, and ``os.path.normcase`` is a no-op there. Resolving the on-disk spelling would need a directory walk
      per component and fails for a folder that does not exist yet, so the guard compares ``casefold``-ed paths. On a
      case-sensitive volume this over-refuses only a sibling that differs by case alone, the safe direction.
    Inputs: path (str). Output: str - NFC-normalised (APFS treats NFC and NFD spellings as one folder), casefolded,
      trailing slashes stripped.
    Example: fold_path('/Users/example/Carnivore-Projects/')  # '/users/example/carnivore-projects'
    """
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
    """Resolve one session's directory onto a project, spelling included.

    Description: the whole ladder. As-written match, then canonical
      match, then - only when asked - a minted project, then the two
      honest refusals.

      ``stored_project_id`` is what the row ALREADY holds, and it is not
      a tie-breaker: it is the reason a refusal may be silent. When the
      ladder ends in ``none`` or ``unknown`` and the row already carries
      a project, this returns that project unchanged with no attribution
      claim to write, so the caller cannot half-overwrite a good row
      with a worse answer. That single rule is what fixes the rows this
      module's docstring names.
    Inputs: conn (sqlite3.Connection) - caller owns the transaction.
      working_dir (str | None) - the probed cwd; None means the probe
      did not answer. stored_project_id (int | None) - the project the
      row already holds, if any. allow_create (bool) - whether the last
      rung may mint a project. now (str | None) - clock for the mint.
      roots (dict[str, int] | None) - project root -> id, read from the
      connection when not supplied. display_name (str | None) - the name a minted project takes.
    Output: ProjectBinding.
    Example:
        resolve_project_binding(conn, '/Users/example/Development/app').rule
    """
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
        # could not
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


def correct_shallow_derivations(
    conn: sqlite3.Connection, *, now: Optional[str] = None
) -> int:
    return sum(
        backfill_sessions_under_root(
            conn, root=root, project_id=pid, now=now, adopt_unassigned=False
        )
        for root, pid in matchable_roots(conn).items()
    )


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
