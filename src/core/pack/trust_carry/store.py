
from __future__ import annotations

import os
import sqlite3
from typing import Iterable, Optional, Tuple

import structlog

from src.core.claude_folder_trust import load_trust_map
from src.core.provider_ledger.credentials import claude_identity_path, is_default_claude_dir
from src.core.trail_entry import utc_now

logger = structlog.get_logger()


def git_top(path: str) -> Optional[Tuple[str, str]]:
    current = os.path.normpath(path)
    while True:
        dotgit = os.path.join(current, ".git")
        if os.path.lexists(dotgit):
            return current, dotgit
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def canonical_root(root: str, dotgit: str) -> str:
    if os.path.isdir(dotgit):
        return root
    try:
        with open(dotgit, "r", encoding="utf-8") as fh:
            line = fh.readline().strip()
        gitdir = os.path.realpath(os.path.join(root, line[len("gitdir:"):].strip())) if line.startswith("gitdir:") else ""
        main_git = os.path.dirname(os.path.dirname(gitdir))
        if gitdir and os.path.basename(os.path.dirname(gitdir)) == "worktrees" and os.path.basename(main_git) == ".git":
            with open(os.path.join(gitdir, "gitdir"), "r", encoding="utf-8") as fh:
                back = os.path.realpath(fh.readline().strip())
            if back == os.path.realpath(dotgit):
                return os.path.dirname(main_git)
    except OSError:
        pass
    return root


def source_trusted(folder: Optional[str], trust_path=None) -> bool:
    trust = load_trust_map(trust_path) if folder else None
    if not trust:
        return False
    cwd = os.path.realpath(folder)
    top = git_top(cwd)
    if trust.get(canonical_root(*top) if top else cwd) is True:
        return True
    stop = top[0] if top else None
    current = cwd
    while True:
        if stop is not None and not (current == stop or current.startswith(stop.rstrip("/") + "/")):
            return False
        if trust.get(current) is True:
            return True
        parent = os.path.dirname(current)
        if current == stop or parent == current:
            return False
        current = parent


def project_trusted(folder: Optional[str], profile_dirs: Iterable[Optional[str]]) -> bool:
    """
    ``profile_dirs`` holds each session's claude config dir: None is the default login, "" is a profile that could not be resolved
    (never trusted). A trust yes lives in that profile's own ``.claude.json``, so a acme session's yes is read there. No session,
    or only default-login sessions, reads the default config exactly as before. EVERY profile must trust it: this never carries a yes
    that a moving session's own profile would not have given.
    Example: project_trusted("/p/app", ["/Users/me/.carnivore/accounts/acme"]) -> True
    """
    dirs = set(profile_dirs) or {None}
    for profile in dirs:
        if profile == "":
            return False
        default = profile is None or is_default_claude_dir(profile)
        if not (source_trusted(folder) if default else source_trusted(folder, claude_identity_path(profile))):
            return False
    return True


def may_carry(folder: str, projects_dir: str) -> bool:
    real, base = os.path.realpath(folder), os.path.realpath(projects_dir)
    return real != base and real.startswith(base.rstrip("/") + "/") and git_top(os.path.dirname(real)) is None


def record(conn: sqlite3.Connection, folder: str, project_uid: str, source_install_id: str, op_id: str, *, projects_dir: str, imports_ok: bool = False) -> bool:
    canonical = canonical_folder(folder)
    if canonical is None or not may_carry(canonical, projects_dir):
        return False
    _insert(conn, canonical, project_uid, source_install_id, op_id, imports_ok)
    return True


def canonical_folder(folder: str) -> Optional[str]:
    if not folder or not os.path.isdir(folder):
        return None
    canonical = os.path.join(os.path.realpath(os.path.dirname(folder)), os.path.basename(folder))
    return canonical if os.path.realpath(folder) == canonical else None


def _insert(conn: sqlite3.Connection, folder: str, project_uid: str, source_install_id: str, op_id: str, imports_ok: bool = False) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO pack_carried_trust (folder, project_uid, source_install_id, op_id, created_at, imports_ok) VALUES (?, ?, ?, ?, ?, ?)",
                     (folder, project_uid, source_install_id, op_id, utc_now(), int(imports_ok)))
    logger.info("pack_trust_carried_recorded", folder=folder, project_uid=project_uid, op_id=op_id)


def inherit(conn: sqlite3.Connection, folder: str, project_uid: str, *, projects_dir: str) -> bool:
    canonical = canonical_folder(folder)
    top = git_top(canonical) if canonical else None
    if canonical is None or top is None or os.path.realpath(top[0]) != canonical:
        return False
    main = os.path.realpath(canonical_root(*top))
    if main == canonical or carried_op(conn, main) is None:
        return False
    parent = conn.execute("SELECT source_install_id, op_id, imports_ok FROM pack_carried_trust WHERE folder = ? AND project_uid = ?", (main, project_uid)).fetchone()
    if parent is None or not may_carry(main, projects_dir):
        return False
    _insert(conn, canonical, project_uid, parent[0], parent[1], bool(parent[2]))
    return True


def forget_op(conn: sqlite3.Connection, op_id: str) -> None:
    with conn:
        conn.execute("DELETE FROM pack_carried_trust WHERE op_id = ?", (op_id,))


def forget_project(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("DELETE FROM pack_carried_trust WHERE project_uid IN (SELECT uid FROM projects WHERE id = ?)", (project_id,))


def carried_op(conn: sqlite3.Connection, folder: str) -> Optional[str]:
    target = os.path.realpath(folder)
    row = conn.execute("SELECT t.folder, t.op_id, t.project_uid, p.root FROM pack_carried_trust t JOIN projects p ON p.uid = t.project_uid "
                       "WHERE t.folder = ? AND p.pack_state != 'moved_away'", (target,)).fetchone()
    if row is None:
        return None
    root = os.path.realpath(str(row[3]))
    if root == target:
        return str(row[1])
    owner = conn.execute("SELECT 1 FROM pack_carried_trust WHERE folder = ? AND project_uid = ? AND op_id = ?", (root, row[2], row[1])).fetchone()
    return str(row[1]) if owner is not None else None


def carried_imports_ok(conn: sqlite3.Connection, folder: str) -> bool:
    if carried_op(conn, folder) is None:
        return False
    row = conn.execute("SELECT imports_ok FROM pack_carried_trust WHERE folder = ?", (os.path.realpath(folder),)).fetchone()
    return bool(row and row[0])
