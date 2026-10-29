
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import (
    ACTION_ATTACH, ACTION_CREATE, ACTION_FOLLOW, B_BAD_MODE, B_BAD_REQUEST, B_NO_SUCH_PROJECT, B_PROJECT_CHOICE,
    B_PROJECT_HOMED_ELSEWHERE, B_PROJECT_NOT_HOME, B_RELOCATE_REQUIRED, B_ROOT_REFUSED, MODE_RELOCATE, MODE_SAME, MODES,
    W_ADOPTION, W_PROJECT_RENAMED, Collector, ImportRequest,
)
from src.core.crate_import.provenance import Provenance
from src.core.project_directory import canonical_path, resolve_project_directory
from src.core.project_move.paths import PathMapping, is_within
from src.core.project_store import normalize_root
from src.core.project_writes import ProjectRootRefused, refuse_unsafe_root
from src.core.session_project_binding import fold_path, plan_adoptions

SENSITIVE_HOME_PARTS: Tuple[str, ...] = ("Library/LaunchAgents", "Library/LaunchDaemons", ".ssh", ".gnupg", ".aws", ".config", ".local")
SENSITIVE_ABSOLUTE: Tuple[str, ...] = ("/etc", "/System", "/usr", "/bin", "/sbin", "/Library", "/Applications", "/private/etc", "/var/db",
                                       "/var/root", "/var/log", "/private/var/db", "/private/var/root", "/private/var/log")


@dataclass(frozen=True)
class CrateProject:

    scope: str
    uid: Optional[str]
    root: Optional[str]
    raw_path: Optional[str]
    name: Optional[str]
    created_epoch: int
    working_dirs: Tuple[str, ...] = ()


@dataclass
class TargetDecision:

    action: Optional[str] = None
    project_id: Optional[int] = None
    name: str = ""
    uid: Optional[str] = None
    root_from: Optional[str] = None
    root_to: Optional[str] = None
    name_changed_to: Optional[str] = None
    suggested_root: Optional[str] = None
    mapping: PathMapping = field(default_factory=lambda: PathMapping.of([]))
    mapping_sources: List[Dict[str, str]] = field(default_factory=list)
    adoptions: List[Dict[str, Any]] = field(default_factory=list)

    def project_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"action": self.action, "id": self.project_id, "name": self.name, "uid": self.uid,
                               "root_from": self.root_from, "root_to": self.root_to,
                               "adoptions": [{"session_id": a["id"], "from_project": a["from_project_id"]} for a in self.adoptions]}
        if self.name_changed_to:
            out["name_changed_to"] = self.name_changed_to
        if self.suggested_root:
            out["suggested_root"] = self.suggested_root
        return out


def crate_date(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y%m%d")


def _real(path: str) -> str:
    return os.path.realpath(path)


def sensitive_root_problem(root: str, home: Optional[str] = None) -> Optional[str]:
    real = _real(root)
    base = _real(home or str(Path.home()))
    if real == base:
        return "is the home folder itself"
    for absolute in SENSITIVE_ABSOLUTE:
        if is_within(real, _real(absolute)):
            return f"sits in the system folder {absolute}"
    for part in SENSITIVE_HOME_PARTS:
        if is_within(real, _real(os.path.join(base, part))):
            return "sits in a sensitive folder"
    return None


def protected_problem(root: str, env: ImportEnv) -> Optional[str]:
    real = _real(root)
    for home in env.protected_homes():
        real_home = _real(str(home))
        if is_within(real, real_home):
            return "is inside a live harness home or the state folder"
        if is_within(real_home, real):
            return "holds a live harness home or the state folder"
    return None


def _project_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT id, root, uid, display_name, pack_state, home_install_id, archived_at FROM projects "
                        "WHERE host_key = 'local'").fetchall()
    return [dict(r) for r in rows]


def _folded(path: str) -> str:
    return fold_path(canonical_path(path) or path)


def _row_at_root(rows: List[Dict[str, Any]], root: str) -> Optional[Dict[str, Any]]:
    want = {_folded(root), fold_path(root)}
    return next((r for r in rows if _folded(r["root"]) in want or fold_path(r["root"]) in want), None)


def _deepest_containing(rows: List[Dict[str, Any]], folder: str) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    for row in rows:
        if (is_within(folder, row["root"]) or is_within(_real(folder), _real(row["root"]))) and (
                best is None or len(Path(row["root"]).parts) > len(Path(best["root"]).parts)):
            best = row
    return best


def _free_name(conn: sqlite3.Connection, name: str, date: str) -> Tuple[str, Optional[str]]:
    taken = {r[0] for r in conn.execute("SELECT display_name FROM projects WHERE host_key = 'local'")}
    if name not in taken:
        return name, None
    candidate, n = f"{name}-{date}", 2
    while candidate in taken:
        candidate, n = f"{name}-{date}-{n}", n + 1
    return candidate, candidate


def _suggested(env: ImportEnv, name: Optional[str]) -> str:
    """The folder offered when a same-path restore is not allowed: ``<projects folder>/<safe name>``. Pure."""
    safe = "".join(ch if (ch.isalnum() or ch in " ._-") else "_" for ch in (name or "restored project")).strip(" .") or "restored project"
    return os.path.join(env.projects_dir, safe)


def home_choice_problem(real: str, env: ImportEnv) -> Optional[str]:
    home = _real(str(env.user_home()))
    if real == home or not is_within(real, home):
        return "is not inside your home folder or this computer's projects folder"
    library = os.path.join(home, "Library")
    if is_within(real, library) and not is_within(real, os.path.join(library, "Mobile Documents")):
        return "sits in a protected folder"
    if any(is_within(real, os.path.join(home, part)) for part in (".claude", ".codex")):
        return "sits in a protected folder"
    return None


def _foreign_root_problem(root: str, env: ImportEnv) -> Optional[str]:
    real, base = _real(root), _real(env.projects_dir)
    if real == base or not is_within(real, base):
        problem = home_choice_problem(real, env)
        if problem is not None:
            return problem
    if os.path.lexists(real) and not os.path.isdir(real):
        return "is a file, not a folder"
    return None


def _mapping_rules(old_roots: List[str], root_to: str, extra: Tuple[Tuple[str, str], ...], env: ImportEnv,
                   crate_homes: Mapping[str, Optional[str]]) -> Tuple[PathMapping, List[Dict[str, str]]]:
    rules: List[Tuple[str, str, str]] = [(old, root_to, "root") for old in dict.fromkeys(o for o in old_roots if o)]
    homes = {"claude": str(env.claude_homes[0]), "codex": str(env.codex_home), "state": str(env.state)}
    rules += [(path, homes[kind], "home") for kind, path in crate_homes.items() if path and kind in homes]
    rules += [(old, new, "rule") for old, new in extra]
    return PathMapping.of([(o, n) for o, n, _ in rules]), [{"from": o, "to": n, "source": s} for o, n, s in rules]


def _foreign_gate(root_to: str, prov: Provenance, env: ImportEnv, rows: List[Dict[str, Any]], col: Collector,
                  out: TargetDecision, code: str, suggest: Optional[str]) -> bool:
    if prov.own:
        return True
    problem = _foreign_root_problem(root_to, env)
    if problem is None:
        return True
    out.suggested_root = _suggested(env, suggest) if code == B_RELOCATE_REQUIRED else None
    col.block(code, f"{root_to} {problem}")
    return False


def _pick_root(crate: CrateProject, request: ImportRequest, prov: Provenance, env: ImportEnv, rows: List[Dict[str, Any]],
               row_by_uid: Optional[Dict[str, Any]], col: Collector, out: TargetDecision) -> Optional[Tuple[str, Optional[Dict[str, Any]], str]]:
    """Choose the root and the project row already there. Output: (root_to, existing row | None, how) with how in ``root``, ``uid``,
    ``picked``; or None when blocked (a blocker is on ``col``)."""
    if crate.scope == "session" and crate.root is None:
        picked = None
        if request.target_project_id is not None:
            picked = next((r for r in rows if r["id"] == request.target_project_id), None)
            if picked is None:
                col.block(B_NO_SUCH_PROJECT, str(request.target_project_id))
                return None
        elif request.mode == MODE_SAME:
            picked = row_by_uid or (_deepest_containing(rows, crate.working_dirs[0]) if crate.working_dirs else None)
            if picked is not None and not _foreign_gate(picked["root"], prov, env, rows, col, out, B_RELOCATE_REQUIRED, crate.name):
                return None
        if picked is not None:
            return picked["root"], picked, "picked"
        if request.mode == MODE_SAME:
            col.block(B_PROJECT_CHOICE, "")
            return None
    if request.mode == MODE_SAME:
        if out.root_from is None:
            col.block(B_PROJECT_CHOICE, "")
            return None
        root_to = normalize_root(out.root_from)
        if not _foreign_gate(root_to, prov, env, rows, col, out, B_RELOCATE_REQUIRED, crate.name):
            return None
    else:
        if not request.new_root:
            col.block(B_BAD_REQUEST, "relocate needs new_root")
            return None
        verdict = resolve_project_directory(request.new_root, None, [env.projects_dir, str(env.user_home())])
        if not verdict.ok or verdict.path is None:
            col.block(B_ROOT_REFUSED, f"{request.new_root}: {verdict.code}")
            return None
        root_to = verdict.path
        if not _foreign_gate(root_to, prov, env, rows, col, out, B_ROOT_REFUSED, None):
            return None
    at_root = _row_at_root(rows, root_to)
    if at_root is not None:
        return at_root["root"], at_root, "root"
    if row_by_uid is not None:
        return row_by_uid["root"], row_by_uid, "uid"
    return root_to, None, "root"


def decide(crate: CrateProject, request: ImportRequest, prov: Provenance, env: ImportEnv, conn: sqlite3.Connection,
           col: Collector, *, live_row_ids: FrozenSet[int] = frozenset(),
           crate_homes: Optional[Mapping[str, Optional[str]]] = None) -> TargetDecision:
    out = TargetDecision(name=crate.name or "restored project", uid=crate.uid)
    if request.mode not in MODES:
        col.block(B_BAD_MODE, request.mode)
        return out
    rows = _project_rows(conn)
    row_by_uid = next((r for r in rows if crate.uid and r["uid"] == crate.uid), None)
    out.root_from = crate.root or (crate.working_dirs[0] if crate.working_dirs else None)
    chosen = _pick_root(crate, request, prov, env, rows, row_by_uid, col, out)
    if chosen is None:
        return out
    root_to, existing, how = chosen
    out.root_to = root_to
    for problem in (sensitive_root_problem(root_to, str(env.user_home())), protected_problem(root_to, env)):
        if problem is not None:
            col.block(B_ROOT_REFUSED, f"{root_to} {problem}")
            out.action = None
            return out
    if existing is not None:
        out.action = ACTION_FOLLOW if how == "uid" else ACTION_ATTACH
        out.project_id, out.name, out.uid = existing["id"], existing["display_name"], existing["uid"] or crate.uid
        if row_by_uid is not None and row_by_uid.get("pack_state") == "replica" and row_by_uid.get("home_install_id"):
            col.block(B_PROJECT_HOMED_ELSEWHERE, f"project {row_by_uid['id']}")
        elif existing.get("pack_state") in ("replica", "moved_away"):
            col.block(B_PROJECT_NOT_HOME, f"project {existing['id']} is {existing['pack_state']} here")
    else:
        try:
            refuse_unsafe_root(conn, root_to)
        except ProjectRootRefused as exc:
            col.block(B_ROOT_REFUSED, str(exc))
            return out
        out.action = ACTION_CREATE
        out.name, changed = _free_name(conn, out.name, crate_date(crate.created_epoch))
        if changed:
            out.name_changed_to = changed
            col.warn(W_PROJECT_RENAMED, changed)
        out.adoptions = plan_adoptions(conn, root=root_to, project_id=-1, skip_ids=live_row_ids)
        if out.adoptions:
            col.warn(W_ADOPTION, f"{len(out.adoptions)} sessions already here would join this project")
    rebase_mapping(out, crate, request, env, crate_homes, root_to)
    return out


def rebase_mapping(out: TargetDecision, crate: CrateProject, request: ImportRequest, env: ImportEnv,
                   crate_homes: Optional[Mapping[str, Optional[str]]], root: str) -> None:
    old_roots = [r for r in (crate.root, os.path.expanduser(crate.raw_path) if crate.raw_path else None) if r]
    if not old_roots:
        old_roots = [wd for wd in crate.working_dirs[:1] if not is_within(wd, root)]
    out.mapping, out.mapping_sources = _mapping_rules(old_roots, root, request.rules, env, crate_homes or {})
