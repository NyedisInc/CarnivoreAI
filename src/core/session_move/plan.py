
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src.core.session_move import files as move_files
from src.core.session_move.source import SOURCE_HOME, SOURCE_TEMP, classify_source

DEST_PROJECT = "project"
DEST_NEW_FOLDER = "new_folder"

REQUIRED_RUNG = "agent"
REQUIRED_CONVERSATION = "resumed"

PANE_ALIVE = "alive"
PANE_UNKNOWN = "unknown"

NOT_MOVABLE = "not_movable"
NO_DESTINATION = "no_destination"
PROJECT_NOT_FOUND = "project_not_found"
DESTINATION_INVALID = "destination_invalid"
DESTINATION_IS_SOURCE = "destination_is_source"
DESTINATION_MOVED_AWAY = "destination_moved_away"
BINDING_DISAGREES = "binding_disagrees"
COLLISION = "collision"
BOTH_GIT = "both_git"
TOO_LARGE = "too_large"
SOURCE_UNREADABLE = "source_unreadable"
NO_CONVERSATION = "no_conversation"
CONVERSATION_MISSING = "conversation_missing"
NOT_A_RESUME = "not_a_resume"
LIVENESS_UNKNOWN = "liveness_unknown"

COLLISION_NAMES_SHOWN = 5


@dataclass
class SessionMovePlan:

    session_uuid: str
    tmux_name: Optional[str]
    tmux_socket: Optional[str]
    row_id: int
    source: Optional[str]
    source_kind: Optional[str]
    destination: Optional[str] = None
    destination_kind: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    creates_folder: bool = False
    claude_session_uuid: Optional[str] = None
    pane_state: str = PANE_UNKNOWN
    files: Dict[str, int] = field(default_factory=dict)
    dirs: List[str] = field(default_factory=list)
    left_behind: List[str] = field(default_factory=list)
    collisions: List[str] = field(default_factory=list)
    refusals: List[Dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals

    @property
    def kills_live_pane(self) -> bool:
        return self.pane_state == PANE_ALIVE

    def refuse(self, code: str, message: str) -> None:
        self.refusals.append({"code": code, "message": message})

    def inventory(self) -> move_files.Inventory:
        return move_files.Inventory(files=dict(self.files), dirs=tuple(self.dirs), left_behind=tuple(self.left_behind))

    def to_wire(self) -> Dict[str, Any]:
        return {
            "session_uuid": self.session_uuid, "tmux_name": self.tmux_name, "source": self.source,
            "source_kind": self.source_kind, "destination": self.destination,
            "destination_kind": self.destination_kind, "project_id": self.project_id,
            "project_name": self.project_name, "creates_folder": self.creates_folder,
            "claude_session_uuid": self.claude_session_uuid, "pane_state": self.pane_state,
            "kills_live_pane": self.kills_live_pane, "file_count": len(self.files),
            "total_bytes": sum(self.files.values()), "left_behind": list(self.left_behind),
            "collisions": list(self.collisions), "ok": self.ok, "refusals": list(self.refusals),
        }


def read_row(conn: sqlite3.Connection, session_uuid: str) -> Optional[Dict[str, Any]]:
    from src.core.hosts.ddl import host_scope

    scope_sql, scope_params = host_scope(conn)
    row = conn.execute(
        "SELECT id, session_uuid, working_dir, project_id, tmux_name, tmux_socket, claude_session_uuid, agent_family "
        "FROM sessions WHERE session_uuid = ? AND archived_at IS NULL" + scope_sql,
        (session_uuid, *scope_params)).fetchone()
    if row is None:
        return None
    keys = ("id", "session_uuid", "working_dir", "project_id", "tmux_name", "tmux_socket",
            "claude_session_uuid", "agent_family")
    return dict(zip(keys, tuple(row)))


def _project_row(conn: sqlite3.Connection, project_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT id, root, display_name FROM projects WHERE id = ? AND archived_at IS NULL",
                       (int(project_id),)).fetchone()
    return None if row is None else {"id": row[0], "root": row[1], "display_name": row[2]}


def _resolve_destination(conn: sqlite3.Connection, plan: SessionMovePlan, *, project_id: Optional[int],
                         new_folder: Optional[str], settings: Any) -> None:
    from src.core.project_directory import canonical_path, resolve_project_directory

    if (project_id is None) == (not new_folder or not str(new_folder).strip()):
        plan.refuse(NO_DESTINATION, "choose one destination: an existing project or a new folder")
        return
    if project_id is not None:
        project = _project_row(conn, project_id)
        if project is None:
            plan.refuse(PROJECT_NOT_FOUND, "that project does not exist or is archived")
            return
        plan.destination_kind, plan.project_id = DEST_PROJECT, int(project["id"])
        plan.project_name, plan.destination = project["display_name"], canonical_path(project["root"])
        if not os.path.isdir(plan.destination):
            plan.refuse(DESTINATION_INVALID, f"the project's folder is not on this computer: {plan.destination}")
        return
    verdict = resolve_project_directory(str(new_folder), settings)
    if not verdict.ok or not verdict.path:
        plan.refuse(DESTINATION_INVALID, verdict.message)
        return
    plan.destination_kind, plan.destination = DEST_NEW_FOLDER, verdict.path
    plan.creates_folder = not os.path.exists(verdict.path)
    plan.project_name = os.path.basename(verdict.path)


def _check_destination(conn: sqlite3.Connection, plan: SessionMovePlan, home: str) -> None:
    from src.core.pack.identity.home import ProjectMovedAway, refuse_if_moved_away
    from src.core.session_project_binding import resolve_project_binding

    dest, source = plan.destination or "", plan.source or ""
    if dest == source or (plan.source_kind == SOURCE_TEMP and dest.startswith(source.rstrip(os.sep) + os.sep)):
        plan.refuse(DESTINATION_IS_SOURCE, "the destination is the session's own folder or inside it")
        return
    if dest == home:
        plan.refuse(DESTINATION_INVALID, "the home folder is not a project folder; choose a folder inside it")
        return
    try:
        refuse_if_moved_away(dest)
    except ProjectMovedAway:
        plan.refuse(DESTINATION_MOVED_AWAY, "that project has moved to another computer")
        return
    if plan.destination_kind == DEST_PROJECT:
        binding = resolve_project_binding(conn, dest)
        if binding.project_id != plan.project_id:
            plan.refuse(BINDING_DISAGREES, "another project already claims that folder, so the session would not stay there")


def _check_files(plan: SessionMovePlan) -> None:
    if plan.source_kind != SOURCE_TEMP or not plan.destination:
        return
    source, dest = Path(plan.source or ""), Path(plan.destination)
    try:
        inv = move_files.inventory(source)
    except OSError as exc:
        plan.refuse(SOURCE_UNREADABLE, f"the session's folder could not be read: {exc.strerror or exc}")
        return
    plan.files, plan.dirs, plan.left_behind = dict(inv.files), list(inv.dirs), list(inv.left_behind)
    if len(inv.files) > move_files.MAX_CARRY_FILES or inv.total_bytes > move_files.MAX_CARRY_BYTES:
        plan.refuse(TOO_LARGE, f"the folder holds {len(inv.files)} files ({inv.total_bytes} bytes), too many to back up first")
    if not dest.exists():
        return
    if move_files.both_git(source, dest):
        plan.refuse(BOTH_GIT, "both folders are git repositories; two repositories are not merged")
    plan.collisions = move_files.collisions(inv, dest)
    if plan.collisions:
        names = ", ".join(plan.collisions[:COLLISION_NAMES_SHOWN])
        more = len(plan.collisions) - COLLISION_NAMES_SHOWN
        plan.refuse(COLLISION, f"the destination already has {names}" + (f" and {more} more" if more > 0 else ""))


def _check_resume(plan: SessionMovePlan, row: Mapping[str, Any], preview: Any, corpus_root: Optional[Path]) -> None:
    from src.core.session_transcript_presence import CONVERSATION_ABSENT, family_conversation_presence

    plan.pane_state = str(getattr(preview, "pane_state", PANE_UNKNOWN) or PANE_UNKNOWN) if preview else PANE_UNKNOWN
    if plan.pane_state == PANE_UNKNOWN:
        plan.refuse(LIVENESS_UNKNOWN, "whether the session is running could not be measured, so it is not moved")
    if not plan.claude_session_uuid:
        plan.refuse(NO_CONVERSATION, "this session has no recorded conversation to resume after the move")
        return
    presence = family_conversation_presence(row.get("agent_family"), plan.claude_session_uuid,
                                            working_dir=plan.source, corpus_root=corpus_root)
    if presence.outcome == CONVERSATION_ABSENT:
        plan.refuse(CONVERSATION_MISSING, "the conversation's transcript is not on this computer, so it cannot be resumed")
    rung = getattr(preview, "projected", None) if preview else None
    if rung is None or getattr(rung, "kind", None) != REQUIRED_RUNG \
            or getattr(rung, "conversation", None) != REQUIRED_CONVERSATION:
        plan.refuse(NOT_A_RESUME, "a restart of this session would not resume its conversation in its agent")


def build_plan(conn: sqlite3.Connection, row: Mapping[str, Any], *, project_id: Optional[int],
               new_folder: Optional[str], settings: Any, preview: Any, home: Optional[str] = None,
               corpus_root: Optional[Path] = None) -> SessionMovePlan:
    """Plan one session move. Reads only; creates nothing.

    Inputs: conn; row (dict) - from :func:`read_row`; project_id (int | None) - an existing project;
      new_folder (str | None) - a folder to move into (created when missing, its parent must exist);
      settings - for the projects root and allowed roots; preview - ``SessionManager.restart_preview``'s
      answer (None when it could not be taken); home (str | None) - the home folder, for tests;
      corpus_root (Path | None) - the claude transcript root, for tests (default ``~/.claude/projects``).
    Output: SessionMovePlan.
    Example: build_plan(conn, row, project_id=4, new_folder=None, settings=settings, preview=p).ok
    """
    from src.core.project_directory import canonical_path, projects_root

    home_real = canonical_path(home or str(Path.home()))
    kind = classify_source(row.get("working_dir"), temp_root=projects_root(settings), home=home_real)
    plan = SessionMovePlan(
        session_uuid=str(row["session_uuid"]), tmux_name=row.get("tmux_name"), tmux_socket=row.get("tmux_socket"),
        row_id=int(row["id"]), source=canonical_path(row["working_dir"]) if row.get("working_dir") else None,
        source_kind=kind, claude_session_uuid=row.get("claude_session_uuid"))
    if kind is None:
        plan.refuse(NOT_MOVABLE, "only a session in a temporary ses_ folder or the home folder can be moved")
        return plan
    _resolve_destination(conn, plan, project_id=project_id, new_folder=new_folder, settings=settings)
    if plan.destination and not plan.refusals:
        _check_destination(conn, plan, home_real)
    _check_files(plan)
    _check_resume(plan, row, preview, corpus_root)
    if kind == SOURCE_HOME:
        plan.left_behind = []
    return plan
