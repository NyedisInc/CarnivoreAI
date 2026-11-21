
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

import structlog

from src.core.pack.jobs import gitio, guards, paths, trash
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import HostState, JobError

log = structlog.get_logger(__name__)

MAX_TIPS = 2000
IGNORED_SHOWN = 20
_HEX = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_INSTALL = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")
_QUIET_IGNORED = {*guards.DEP_DIR_NAMES, "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".DS_Store"}
_QUIET_FOLDED = {n.casefold() for n in _QUIET_IGNORED}

PanesFn = Callable[[], Any]
TrashFn = Callable[[Path], trash.TrashResult]


@dataclass(frozen=True)
class CopyVerdict:

    verdict: Literal["deletable", "deleted", "kept"]
    code: str
    root: str
    ignored: Tuple[str, ...] = field(default_factory=tuple)
    ignored_more: int = 0

    def wire(self) -> Dict[str, Any]:
        return {"verdict": self.verdict, "code": self.code, "root": self.root, "ignored": list(self.ignored), "ignored_more": self.ignored_more}


@dataclass
class _Env:

    store: JobStore
    open_db: Callable[[], sqlite3.Connection]
    read_panes: PanesFn
    state_dir: str
    jobs_root: str
    now: float


def _env(store: Optional[JobStore], open_db: Optional[Callable[[], sqlite3.Connection]], read_panes: Optional[PanesFn],
         state_dir: Optional[Path], jobs_root: Optional[Path], now: Optional[float]) -> _Env:
    import time

    from src.api import projects_service
    from src.api.project_move_routes import read_live_panes
    from src.config import settings

    state = Path(state_dir) if state_dir is not None else Path(settings.get_state_dir())
    return _Env(store=store or JobStore(state), open_db=open_db or (lambda: projects_service.open_db_or_503(settings)),
                read_panes=read_panes or read_live_panes, state_dir=os.path.realpath(state),
                jobs_root=os.path.realpath(jobs_root if jobs_root is not None else paths.default_jobs_root()),
                now=now if now is not None else time.time())


def _kept(code: str, root: str = "") -> CopyVerdict:
    return CopyVerdict("kept", code, root)


def _unsafe_root(root: str, env: _Env) -> bool:
    from src.core.project_move.paths import is_within

    if not os.path.isabs(root) or os.path.islink(root):
        return True
    real = os.path.realpath(root)
    if len(Path(real).parts[1:]) < 3 or not os.path.isdir(real):
        return True
    dot_git = os.path.join(real, ".git")
    if os.path.islink(dot_git) or not os.path.isdir(dot_git):
        return True
    if is_within(os.path.realpath(Path.home()), real):
        return True
    return any(is_within(guarded, real) or is_within(real, guarded) for guarded in (env.state_dir, env.jobs_root))


def _resolve(project_uid: str, home_install_id: str, env: _Env) -> "Tuple[Optional[CopyVerdict], Optional[Dict[str, Any]]]":
    from src.core.pack.identity import home

    if not _INSTALL.match(home_install_id or ""):
        return _kept("not_a_copy"), None
    with closing(env.open_db()) as conn:
        row = conn.execute("SELECT id, display_name, root, pack_state, home_install_id, archived_at, host_key FROM projects WHERE uid = ?",
                           (project_uid,)).fetchone()
    if row is None or row["host_key"] != "local" or row["archived_at"] or row["pack_state"] != home.REPLICA \
            or row["home_install_id"] != home_install_id or not row["root"]:
        return _kept("not_a_copy"), None
    root = os.path.realpath(row["root"])
    record = env.store.made_copy_get(root)
    if record is None:
        return _kept("no_record", root), None
    if record["project_uid"] != project_uid or record["home_install_id"] != home_install_id:
        return _kept("not_a_copy", root), None
    if not (record["auto"] and record["folder_made"]):
        return _kept("no_record", root), None
    if _unsafe_root(row["root"], env):
        return _kept("not_a_copy", root), None
    return None, {"root": root, "project_id": row["id"], "project_name": row["display_name"], "literal_root": row["root"]}


def _busy(env: _Env, project_uid: str) -> bool:
    live_host = (HostState.PREPARING, HostState.RUNNING)
    for job in env.store.host_list():
        if job.project_uid == project_uid and (job.state in live_host or (job.keep_until or 0) > env.now):
            return True
    if any(r["job_id"] or (r["keep_until"] or 0) > env.now for r in env.store.slot_rows(project_uid)):
        return True
    return bool(env.store.list_jobs(project_uid=project_uid, live_only=True, limit=1))


def _session_live(root: str, project: Dict[str, Any], env: _Env) -> bool:
    from src.core.project_move.plan import LOCAL_HOST, MovePlan, _live_checks, _rows_under
    from src.core.companion_shell.rows import companion_labels

    literal = project["literal_root"]
    plan = MovePlan(project={"id": project["project_id"], "name": project["project_name"], "root": literal}, new_root=None, move_folder=False)
    with closing(env.open_db()) as conn:
        rows = _rows_under(conn, "sessions", "working_dir", literal, f" AND host_key = '{LOCAL_HOST}'")
        _live_checks(plan, rows, env.read_panes(), companion_labels(conn))
    return not plan.ok


def _git(root: str, *words: str, stdin: Optional[bytes] = None) -> str:
    return gitio.out(gitio.run(["-C", root, "--no-optional-locks", *words], input=stdin, timeout=120.0))


def _slot_paths(env: _Env, project_uid: str) -> Dict[str, str]:
    from src.core.project_move.paths import is_within

    base = os.path.join(env.jobs_root, "folders")
    return {os.path.realpath(r["path"]): r["path"] for r in env.store.slot_rows(project_uid) if is_within(os.path.realpath(r["path"]), base)}


def _unknown_worktrees(root: str, env: _Env, project_uid: str) -> bool:
    known = _slot_paths(env, project_uid)
    entries = [os.path.realpath(line[9:]) for line in _git(root, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]
    return any(p != root and p not in known for p in entries)


def _ignored(root: str) -> Tuple[Tuple[str, ...], int]:
    names: List[str] = []
    for line in _git(root, "status", "--porcelain", "--ignored").splitlines():
        if line.startswith("!! "):
            path = line[3:].rstrip("/")
            if path.split("/")[-1].casefold() not in _QUIET_FOLDED:
                names.append(path)
    return tuple(names[:IGNORED_SHOWN]), max(0, len(names) - IGNORED_SHOWN)


def _git_checks(root: str, home_install_id: str, tips: List[str], env: _Env, project_uid: str) -> "Optional[str]":
    if _git(root, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"):
        return "dirty"
    if _git(root, "for-each-ref", "refs/stash"):
        return "stash"
    present = [line.split()[0] for line in _git(root, "cat-file", "--batch-check", stdin="".join(f"{t}\n" for t in tips).encode()).splitlines()
               if len(line.split()) >= 2 and line.split()[1] != "missing"]
    lonely = _git(root, "rev-list", "--max-count=1", "HEAD", "--branches", "--tags", "--not", f"--glob=refs/carnivore/{home_install_id}/*",
                  "--stdin", stdin="".join(f"^{t}\n" for t in present).encode())
    if lonely:
        return "unseen_commits"
    if _unknown_worktrees(root, env, project_uid):
        return "worktrees"
    return None


def _check(project_uid: str, home_install_id: str, tips: List[str], env: _Env) -> "Tuple[CopyVerdict, Optional[Dict[str, Any]]]":
    kept, copy = _resolve(project_uid, home_install_id, env)
    if copy is None:
        assert kept is not None
        return kept, None
    root = copy["root"]
    if len(tips) > MAX_TIPS:
        return _kept("too_many_refs", root), copy
    if any(not isinstance(t, str) or not _HEX.match(t) for t in tips):
        return _kept("git_failed", root), copy
    if _busy(env, project_uid):
        return _kept("job_running", root), copy
    if _session_live(root, copy, env):
        return _kept("session_live", root), copy
    try:
        code = _git_checks(root, home_install_id, tips, env, project_uid)
        ignored, more = _ignored(root) if code is None else ((), 0)
    except JobError as exc:
        log.warning("pack_copy_check_git", code=exc.code)
        return _kept("git_failed", root), copy
    if code is not None:
        return _kept(code, root), copy
    return CopyVerdict("deletable", "", root, ignored, more), copy


def check(project_uid: str, home_install_id: str, tips: List[str], *, store: Optional[JobStore] = None,
          open_db: Optional[Callable[[], sqlite3.Connection]] = None, read_panes: Optional[PanesFn] = None,
          state_dir: Optional[Path] = None, jobs_root: Optional[Path] = None, now: Optional[float] = None) -> CopyVerdict:
    return _check(project_uid, home_install_id, list(tips), _env(store, open_db, read_panes, state_dir, jobs_root, now))[0]


def _remove_idle_slots(env: _Env, project_uid: str, repo_root: str) -> None:
    from src.core.pack.jobs import folders

    for real, stored in _slot_paths(env, project_uid).items():
        if env.store.slot_drop_idle(stored, env.now):
            folders._remove_slot(repo_root, real)


def forget(project_uid: str, home_install_id: str, tips: List[str], *, store: Optional[JobStore] = None,
           open_db: Optional[Callable[[], sqlite3.Connection]] = None, read_panes: Optional[PanesFn] = None,
           state_dir: Optional[Path] = None, jobs_root: Optional[Path] = None, now: Optional[float] = None,
           trasher: Optional[TrashFn] = None) -> CopyVerdict:
    env = _env(store, open_db, read_panes, state_dir, jobs_root, now)
    verdict, copy = _check(project_uid, home_install_id, list(tips), env)
    if verdict.verdict != "deletable" or copy is None:
        return verdict
    root = copy["root"]
    try:
        _remove_idle_slots(env, project_uid, root)
        verdict, copy = _check(project_uid, home_install_id, list(tips), env)
        if verdict.verdict != "deletable" or copy is None:
            return verdict
        moved = (trasher or (lambda p: trash.move(p, now=datetime.now())))(Path(root))
    except trash.TrashRefused as exc:
        return _kept(exc.code, root)
    except JobError as exc:
        log.warning("pack_copy_forget_git", code=exc.code)
        return _kept("git_failed", root)
    code = _after_move(project_uid, home_install_id, copy, env)
    log.info("pack_copy_forgotten", project_uid=project_uid, kind=moved.kind)
    return CopyVerdict("deleted", code, root, verdict.ignored, verdict.ignored_more)


def _after_move(project_uid: str, home_install_id: str, copy: Dict[str, Any], env: _Env) -> str:
    from src.core.pack.identity import replicas
    from src.core.project_archive import archive_project
    from src.core.project_writes import ProjectNotFound

    env.store.made_copy_delete(copy["root"])
    try:
        with closing(env.open_db()) as conn:
            replicas.detach_replica(conn, home_install_id=home_install_id, project_uid=project_uid)
            archive_project(conn, copy["project_id"])
    except (replicas.ReplicaRefused, ProjectNotFound, sqlite3.Error) as exc:
        log.error("pack_copy_rows_left", error=type(exc).__name__)
        return "row_left"
    return ""


def record_made(store: JobStore, *, root: str, project_uid: str, home_install_id: str, auto: bool, folder_made: bool) -> bool:
    from src.core.trail_entry import utc_now

    real = os.path.realpath(root)
    old = store.made_copy_get(real)
    if old is not None and old["project_uid"] == project_uid and old["home_install_id"] == home_install_id:
        return False
    store.made_copy_put(real, project_uid=project_uid, home_install_id=home_install_id, auto=bool(auto), folder_made=bool(folder_made),
                        created_at=utc_now())
    return True
