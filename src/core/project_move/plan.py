
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.core.claude_project_dirs import path_spellings
from src.core.companion_shell.rows import companion_labels, shell_label
from src.core.db import table_exists
from src.core.db_models import SESSION_LIFECYCLE_STOPPED
from src.core.project_move import claude_side
from src.core.project_move.fingerprint import plan_fingerprint
from src.core.project_move.ledgers import plan_install_rows
from src.core.project_move.paths import is_within, prefix_params, prefix_where, rebase
from src.core.project_move.target import new_root_checks

LOCAL_HOST = "local"


@dataclass(frozen=True)
class PaneListing:

    ok: bool
    panes: Tuple[Tuple[str, Optional[int], Optional[str]], ...] = ()
    reason: str = ""


@dataclass
class MovePlan:

    project: Dict[str, Any]
    new_root: Optional[str]
    move_folder: bool
    new_root_typed: str = ""
    create_parents: bool = False
    folders_to_create: List[str] = field(default_factory=list)
    checks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    children: List[Dict[str, Any]] = field(default_factory=list)
    sessions: List[Dict[str, Any]] = field(default_factory=list)
    conversation_rows: int = 0
    transcript_moves: List[Dict[str, Any]] = field(default_factory=list)
    informational: Dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    skill_installs: Dict[str, int] = field(default_factory=lambda: {"items": 0, "files": 0})

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    @property
    def old_root(self) -> str:
        return self.project["root"]

    def failed(self) -> List[str]:
        return [c["message"] for c in self.checks if not c["ok"]]

    def check(self, check_id: str, ok: bool, message: str) -> bool:
        self.checks.append({"id": check_id, "ok": bool(ok), "message": message})
        return bool(ok)


def _rows_under(conn: sqlite3.Connection, table: str, column: str, root: str, extra: str = "") -> List[sqlite3.Row]:
    sql = f"SELECT * FROM {table} WHERE {prefix_where(column)}{extra}"
    return conn.execute(sql, prefix_params(root)).fetchall()


def _identity_checks(conn: sqlite3.Connection, plan: MovePlan, moved_ids: Sequence[int]) -> None:
    targets = [plan.new_root] + [c["new_root"] for c in plan.children]
    marks = ",".join("?" * len(targets))
    ids = ",".join("?" * len(moved_ids))
    taken = conn.execute(
        f"SELECT display_name, root FROM projects WHERE root IN ({marks}) AND id NOT IN ({ids})",
        (*targets, *moved_ids),
    ).fetchall()
    plan.check("new_root_free", not taken, "no other project owns the new folder" if not taken else
               "already a project: " + "; ".join(f"{r['display_name']} at {r['root']}" for r in taken))
    stones: List[str] = []
    if table_exists(conn, "project_tombstones"):
        stones = [r["root"] for r in conn.execute(
            f"SELECT root FROM project_tombstones WHERE root IN ({marks})", targets)]
    plan.check("new_root_not_tombstoned", not stones, "no deleted project's tombstone matches" if not stones
               else "a deleted project's tombstone would hide it: " + "; ".join(stones))


def _live_checks(plan: MovePlan, session_rows: Sequence[sqlite3.Row], panes: PaneListing, labels: Dict[str, str]) -> None:
    old = plan.old_root
    old_spellings = {old, os.path.realpath(old)}
    live: Dict[str, str] = {}
    instances = {(r["tmux_name"], r["tmux_created_epoch"]) for r in session_rows if r["tmux_name"]}
    for row in session_rows:
        if row["lifecycle"] != SESSION_LIFECYCLE_STOPPED:
            name = row["tmux_name"] or row["title"] or row["session_uuid"]
            live.setdefault(shell_label(name, labels), row["lifecycle"])
    if plan.check("tmux_listing", panes.ok, "the live pane listing answered" if panes.ok
                  else f"the live pane listing did not answer ({panes.reason}); cannot rule out a live pane"):
        for name, epoch, cwd in panes.panes:
            in_old = bool(cwd) and any(is_within(cwd, s) for s in old_spellings)
            if (name, epoch) in instances or in_old:
                live.setdefault(shell_label(name, labels), "live pane")
    plan.check("no_live_sessions", not live, "no live session under the old folder" if not live
               else "stop these sessions first: " + ", ".join(f"{n} ({why})" for n, why in live.items()))


def _transcript_plan(conn: sqlite3.Connection, plan: MovePlan, roots: Optional[Iterable[Path]]) -> None:
    old, new = plan.old_root, plan.new_root
    folders = sorted({old} | {c["old_root"] for c in plan.children} | {s["old_dir"] for s in plan.sessions})
    foreign = [r["root"] for r in conn.execute("SELECT root FROM projects")] + [
        r["working_dir"] for r in conn.execute("SELECT DISTINCT working_dir FROM sessions WHERE working_dir IS NOT NULL")]
    foreign = [p for p in foreign if not is_within(p, old)]
    plan.transcript_moves, conflicts = claude_side.transcript_moves(
        [(p, rebase(p, old, new)) for p in folders],
        claude_side.transcript_roots() if roots is None else roots, foreign)
    plan.check("transcript_targets_free", not conflicts, "every transcript folder can be renamed" if not conflicts
               else "; ".join(conflicts))


def build_plan(
    conn: sqlite3.Connection,
    project: Dict[str, Any],
    new_root_raw: str,
    move_folder: bool,
    *,
    panes: PaneListing,
    settings: Any,
    roots: Optional[Iterable[Path]] = None,
    claude_json: Optional[Iterable[Path]] = None,
    create_parents: bool = False,
) -> MovePlan:
    plan = MovePlan(
        project={"id": project["id"], "name": project["display_name"], "root": project["root"]},
        new_root=None, move_folder=bool(move_folder), new_root_typed=new_root_raw,
        create_parents=bool(create_parents),
    )
    old = plan.old_root
    new = new_root_checks(plan, new_root_raw, settings)
    plan.new_root = new
    rebasable = new is not None and new != old and not is_within(new, old)

    def moved(path: str) -> Optional[str]:
        return rebase(path, old, new) if rebasable else None

    local = f" AND host_key = '{LOCAL_HOST}'"
    child_rows = [r for r in _rows_under(conn, "projects", "root", old, local) if r["id"] != project["id"]]
    plan.children = [{"id": r["id"], "name": r["display_name"], "old_root": r["root"],
                      "new_root": moved(r["root"])} for r in child_rows]
    session_rows = _rows_under(conn, "sessions", "working_dir", old, local)
    plan.sessions = [{"id": r["id"], "name": r["tmux_name"] or r["title"], "lifecycle": r["lifecycle"],
                      "old_dir": r["working_dir"], "new_dir": moved(r["working_dir"])}
                     for r in session_rows]
    _live_checks(plan, session_rows, panes, companion_labels(conn))
    plan_install_rows(conn, plan, rebasable)
    if table_exists(conn, "conversation_index"):
        plan.conversation_rows = len(_rows_under(conn, "conversation_index", "working_dir", old))
    moving = [old] + [c["old_root"] for c in plan.children]
    if rebasable:
        _identity_checks(conn, plan, [project["id"]] + [c["id"] for c in plan.children])
        _transcript_plan(conn, plan, roots)
    else:
        plan.warnings.append("transcript folders and the new folder's owner were not measured: "
                             "the new folder is not usable yet (see the failed checks)")
    now_at = new if new and rebasable and Path(new).is_dir() else old
    plan.informational = {
        "settings_files_naming_old_folder": claude_side.settings_mentions(
            [now_at] + [rebase(c["old_root"], old, now_at) for c in plan.children], old),
        "transcript_spellings_searched": path_spellings(old),
        "claude_json_trust_keys": claude_side.trust_keys(
            claude_side.claude_json_files() if claude_json is None else claude_json, moving),
        "note": "these are never edited; carried folder trust moves only on carnivore's own record, and claude asks once in the new place otherwise",
    }
    plan.fingerprint = plan_fingerprint(plan)
    return plan
