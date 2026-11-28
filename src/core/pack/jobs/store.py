
from __future__ import annotations

import dataclasses
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple

import structlog

from src.core.db_reuse.thread_connections import ThreadConnections
from src.core.pack.jobs import ddl
from src.core.pack.jobs.install import InstallRow
from src.core.pack.jobs.view import WARM_PREFIX
from src.core.pack.jobs.types import TERMINAL, HostJob, HostState, JobError, JobRecord, JobState

def _open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    for stmt in ddl.DDL:
        conn.execute(stmt)
    ddl.migrate(conn)
    return conn


_POOL = ThreadConnections(_open, limit=4)
_DEPTH = threading.local()
_JOB_COLS = [f.name for f in dataclasses.fields(JobRecord)]
_HOST_COLS = [f.name for f in dataclasses.fields(HostJob)]
_POLICY_COLS = {"auto_delegate", "never_use_json", "carry_json", "bring_back_json", "setup_json", "local_only_json"}
_SSH_TARGET_COLS = {"takes_work", "pinned_fp", "far_root", "login_shell", "path_extra_json", "can_json", "probed_at", "reserve_json", "labels_json",
                    "last_ok", "last_error", "updated_at"}
_TERMINAL_VALUES = tuple(s.value for s in TERMINAL)
_MADE_COPY_COLS = {"project_uid", "home_install_id", "auto", "folder_made", "created_at"}
_HOST_LIVE = (HostState.PREPARING.value, HostState.RUNNING.value, HostState.PARKED.value)
log = structlog.get_logger(__name__)
_HOST_PLACE_COLS = {"caller_install", "project_uid", "session_id", "session_uuid", "answer"}
_PLACEMENT_COLS = {"project_uid", "install_id", "label", "decision", "session_id", "session_uuid", "reason", "starter_kind"}


def _job(row: sqlite3.Row) -> JobRecord:
    data = dict(row)
    data["state"] = JobState(data["state"])
    return JobRecord(**data)


def _host(row: sqlite3.Row) -> HostJob:
    data = dict(row)
    data["state"] = HostState(data["state"])
    return HostJob(**data)


def _plain(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


class JobStore:

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self._path = self.state_dir / ddl.FILENAME
        self.on_change: Optional[Callable[[str, bool], None]] = None
        self.on_removed: Optional[Callable[[List[str]], None]] = None

    def _fire(self, hook: Optional[Callable[..., None]], *args: Any) -> None:
        if hook is None:
            return
        try:
            hook(*args)
        except Exception as exc:  # noqa: BLE001
            log.warning("pack_jobs_hook_failed", error=type(exc).__name__)

    def _connect(self) -> sqlite3.Connection:
        return _open(self._path)

    @contextmanager
    def _borrow(self) -> Iterator[sqlite3.Connection]:
        conn = _POOL.get(self._path)
        depth = getattr(_DEPTH, "n", 0)
        _DEPTH.n = depth + 1
        broken = False
        try:
            yield conn
        except sqlite3.DatabaseError:
            broken = depth == 0
            raise
        finally:
            _DEPTH.n = depth
            if broken:
                _POOL.discard(self._path)
            elif depth == 0 and conn.in_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    _POOL.discard(self._path)

    @contextmanager
    def _tx(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        with self._borrow() as conn:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")


    def create_job(self, rec: JobRecord) -> JobRecord:
        now = time.time()
        rec = dataclasses.replace(rec, created_at=rec.created_at or now, updated_at=rec.updated_at or now)
        cols = ",".join(_JOB_COLS)
        marks = ",".join("?" for _ in _JOB_COLS)
        with self._tx() as conn:
            conn.execute(f"INSERT INTO jobs ({cols}) VALUES ({marks})", [_plain(getattr(rec, c)) for c in _JOB_COLS])
            conn.execute("INSERT INTO job_events (job_id, at, state, note) VALUES (?,?,?,?)",
                         (rec.id, rec.created_at, _plain(rec.state), "created"))
        self._fire(self.on_change, rec.id, True)
        return rec

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _job(row) if row else None

    def find_live_by_idem(self, key: str) -> Optional[JobRecord]:
        marks = ",".join("?" for _ in _TERMINAL_VALUES)
        with self._borrow() as conn:
            row = conn.execute(f"SELECT * FROM jobs WHERE idem_key=? AND state NOT IN ({marks}) ORDER BY created_at DESC LIMIT 1",
                               (key, *_TERMINAL_VALUES)).fetchone()
        return _job(row) if row else None

    def set_state(self, job_id: str, state: JobState, *, note: str = "", **fields: Any) -> JobRecord:
        bad = set(fields) - (set(_JOB_COLS) - {"id", "state"})
        if bad:
            raise TypeError(f"not a jobs column: {sorted(bad)}")
        now = time.time()
        state = JobState(state)
        if state in TERMINAL and "ended_at" not in fields:
            fields["ended_at"] = now
        fields["updated_at"] = now
        sets = ",".join(f"{c}=?" for c in ["state", *fields])
        with self._tx() as conn:
            row = conn.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise JobError("unknown_job", "no such job", 404)
            if JobState(row["state"]) in TERMINAL:
                raise JobError("job_ended", f"the job already ended ({row['state']})")
            moved = row["state"] != state.value
            conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", [state.value, *[_plain(v) for v in fields.values()], job_id])
            conn.execute("INSERT INTO job_events (job_id, at, state, note) VALUES (?,?,?,?)", (job_id, now, state.value, note))
        self._fire(self.on_change, job_id, moved)
        rec = self.get_job(job_id)
        assert rec is not None
        return rec

    def list_jobs(self, *, limit: int = 50, project_uid: Optional[str] = None, live_only: bool = False,
                  before: Optional[Tuple[float, str]] = None, caller: Optional[str] = None) -> List[JobRecord]:
        where: List[str] = []
        args: List[Any] = []
        if project_uid is not None:
            where.append("project_uid=?")
            args.append(project_uid)
        if caller is not None:
            where.append("caller_session=?")
            args.append(caller)
        if live_only:
            where.append(f"state NOT IN ({','.join('?' for _ in _TERMINAL_VALUES)})")
            args.extend(_TERMINAL_VALUES)
        if before is not None:
            where.append("(created_at<? OR (created_at=? AND id<?))")
            args.extend([before[0], before[0], before[1]])
        sql = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC, id DESC LIMIT ?"
        with self._borrow() as conn:
            return [_job(r) for r in conn.execute(sql, (*args, int(limit))).fetchall()]

    def host_page(self, *, limit: int = 50, project_uid: Optional[str] = None, live_only: bool = False,
                  before: Optional[Tuple[float, str]] = None) -> List[HostJob]:
        where, args = ["job_id NOT LIKE ?"], [WARM_PREFIX + "%"]
        if project_uid is not None:
            where.append("project_uid=?")
            args.append(project_uid)
        if live_only:
            where.append(f"state IN ({','.join('?' for _ in _HOST_LIVE)})")
            args.extend(_HOST_LIVE)
        if before is not None:
            where.append("(created_at<? OR (created_at=? AND job_id<?))")
            args.extend([before[0], before[0], before[1]])
        sql = "SELECT * FROM host_jobs WHERE " + " AND ".join(where) + " ORDER BY created_at DESC, job_id DESC LIMIT ?"
        with self._borrow() as conn:
            return [_host(r) for r in conn.execute(sql, (*args, int(limit))).fetchall()]

    def list_page(self, *, limit: int = 50, project_uid: Optional[str] = None, live_only: bool = False,
                  before: Optional[Tuple[float, str]] = None, caller: Optional[str] = None) -> Tuple[List[Any], bool]:
        rows: List[Any] = self.list_jobs(limit=limit + 1, project_uid=project_uid, live_only=live_only, before=before, caller=caller)
        if caller is None:
            rows += self.host_page(limit=limit + 1, project_uid=project_uid, live_only=live_only, before=before)
        rows.sort(key=lambda r: (r.created_at, getattr(r, "id", None) or r.job_id), reverse=True)
        return rows[:limit], len(rows) > limit

    def sweep_rows(self) -> List[JobRecord]:
        sql = "SELECT * FROM jobs WHERE state IN ('waiting_approval','lost') OR (state='done' AND land_json IS NOT NULL)"
        with self._borrow() as conn:
            return [_job(r) for r in conn.execute(sql).fetchall()]

    def purge_before(self, cutoff: float) -> int:
        marks = ",".join("?" for _ in _TERMINAL_VALUES)
        old = f"SELECT id FROM jobs WHERE state IN ({marks}) AND COALESCE(ended_at, updated_at) < ?"
        with self._tx() as conn:
            gone = [r["id"] for r in conn.execute(old, (*_TERMINAL_VALUES, cutoff)).fetchall()]
            conn.execute(f"DELETE FROM job_events WHERE job_id IN ({old})", (*_TERMINAL_VALUES, cutoff))
            count = conn.execute(f"DELETE FROM jobs WHERE id IN ({old})", (*_TERMINAL_VALUES, cutoff)).rowcount
        if gone:
            self._fire(self.on_removed, gone)
        return count

    def events(self, job_id: str) -> List[dict]:
        with self._borrow() as conn:
            rows = conn.execute("SELECT at, state, note FROM job_events WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
        return [dict(r) for r in rows]


    def host_put(self, row: HostJob) -> HostJob:
        row = dataclasses.replace(row, created_at=row.created_at or time.time())
        cols = ",".join(_HOST_COLS)
        marks = ",".join("?" for _ in _HOST_COLS)
        with self._tx() as conn:
            made = conn.execute(f"INSERT OR IGNORE INTO host_jobs ({cols}) VALUES ({marks})", [_plain(getattr(row, c)) for c in _HOST_COLS]).rowcount
            got = conn.execute("SELECT * FROM host_jobs WHERE job_id=?", (row.job_id,)).fetchone()
        if made:
            self._fire(self.on_change, row.job_id, True)
        return _host(got)

    def host_get(self, job_id: str) -> Optional[HostJob]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM host_jobs WHERE job_id=?", (job_id,)).fetchone()
        return _host(row) if row else None

    def host_set(self, job_id: str, **fields: Any) -> HostJob:
        bad = set(fields) - (set(_HOST_COLS) - {"job_id"})
        if bad:
            raise TypeError(f"not a host_jobs column: {sorted(bad)}")
        moved = False
        with self._tx() as conn:
            before = conn.execute("SELECT state FROM host_jobs WHERE job_id=?", (job_id,)).fetchone()
            if fields:
                sets = ",".join(f"{c}=?" for c in fields)
                conn.execute(f"UPDATE host_jobs SET {sets} WHERE job_id=?", [*[_plain(v) for v in fields.values()], job_id])
            row = conn.execute("SELECT * FROM host_jobs WHERE job_id=?", (job_id,)).fetchone()
            if before is not None and "state" in fields:
                moved = before["state"] != row["state"]
        if row is None:
            raise JobError("unknown_job", "no such job", 404)
        if fields:
            self._fire(self.on_change, job_id, moved)
        return _host(row)

    def host_list(self, states: Optional[Sequence[HostState]] = None) -> List[HostJob]:
        sql, args = "SELECT * FROM host_jobs", []
        if states is not None:
            args = [_plain(s) for s in states]
            sql += f" WHERE state IN ({','.join('?' for _ in args)})"
        with self._borrow() as conn:
            return [_host(r) for r in conn.execute(sql + " ORDER BY created_at, rowid", args).fetchall()]

    def host_delete(self, job_id: str) -> None:
        with self._tx() as conn:
            gone = conn.execute("DELETE FROM host_jobs WHERE job_id=?", (job_id,)).rowcount
        if gone:
            self._fire(self.on_removed, [job_id])


    def slot_claim(self, project_uid: str, repo_root: str, path_for: Callable[[int], str], job_id: str, *,
                   max_slots: int = 3) -> Optional[Tuple[int, str, bool]]:
        now = time.time()
        with self._tx() as conn:
            free = conn.execute("SELECT path, slot FROM slots WHERE project_uid=? AND job_id IS NULL AND (keep_until IS NULL OR keep_until<=?)"
                                " ORDER BY slot LIMIT 1", (project_uid, now)).fetchone()
            if free is not None:
                conn.execute("UPDATE slots SET job_id=?, repo_root=?, keep_until=NULL, last_used=? WHERE path=?",
                             (job_id, repo_root, now, free["path"]))
                return int(free["slot"]), free["path"], False
            count, top = conn.execute("SELECT COUNT(*), COALESCE(MAX(slot), 0) FROM slots WHERE project_uid=?", (project_uid,)).fetchone()
            if count >= max_slots:
                return None
            n = int(top) + 1
            path = path_for(n)
            conn.execute("INSERT INTO slots (path, project_uid, slot, repo_root, job_id, last_used) VALUES (?,?,?,?,?,?)",
                         (path, project_uid, n, repo_root, job_id, now))
            return n, path, True

    def slot_free(self, path: str, *, memo: Optional[dict] = None, keep_until: Optional[float] = None) -> None:
        with self._tx() as conn:
            if memo is not None:
                conn.execute("UPDATE slots SET memo_json=? WHERE path=?", (json.dumps(memo, sort_keys=True), path))
            conn.execute("UPDATE slots SET job_id=NULL, keep_until=?, last_used=? WHERE path=?", (keep_until, time.time(), path))

    def slot_rows(self, project_uid: Optional[str] = None) -> List[dict]:
        sql, args = "SELECT * FROM slots", []
        if project_uid is not None:
            sql, args = sql + " WHERE project_uid=?", [project_uid]
        with self._borrow() as conn:
            rows = conn.execute(sql + " ORDER BY project_uid, slot", args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["memo"] = json.loads(d["memo_json"]) if d["memo_json"] else {}
            out.append(d)
        return out

    def slot_drop(self, path: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM slots WHERE path=?", (path,))

    def slot_drop_idle(self, path: str, now: float) -> bool:
        with self._tx() as conn:
            cur = conn.execute("DELETE FROM slots WHERE path=? AND job_id IS NULL AND (keep_until IS NULL OR keep_until<=?)", (path, now))
        return cur.rowcount == 1


    def policy_row(self, project_uid: str) -> Optional[dict]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM project_policy WHERE project_uid=?", (project_uid,)).fetchone()
        return dict(row) if row else None

    def policy_upsert(self, project_uid: str, **cols: Any) -> None:
        bad = set(cols) - _POLICY_COLS
        if bad:
            raise TypeError(f"not a project_policy column: {sorted(bad)}")
        with self._tx() as conn:
            conn.execute("INSERT OR IGNORE INTO project_policy (project_uid) VALUES (?)", (project_uid,))
            if cols:
                conn.execute(f"UPDATE project_policy SET {','.join(f'{c}=?' for c in cols)} WHERE project_uid=?", [*cols.values(), project_uid])

    def auto_replica_add(self, project_uid: str, install_id: str) -> None:
        with self._tx() as conn:
            conn.execute("INSERT OR IGNORE INTO auto_replicas (project_uid, install_id, created_at) VALUES (?,?,?)",
                         (project_uid, install_id, time.time()))

    def auto_replica_list(self, project_uid: str) -> List[str]:
        with self._borrow() as conn:
            rows = conn.execute("SELECT install_id FROM auto_replicas WHERE project_uid=? ORDER BY created_at, install_id", (project_uid,)).fetchall()
        return [r["install_id"] for r in rows]

    def auto_replica_delete(self, project_uid: str, install_id: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM auto_replicas WHERE project_uid=? AND install_id=?", (project_uid, install_id))


    def base_get(self, project_uid: str, peer_install_id: str) -> Optional[str]:
        with self._borrow() as conn:
            row = conn.execute("SELECT commit_sha FROM peer_bases WHERE project_uid=? AND peer_install_id=?", (project_uid, peer_install_id)).fetchone()
        return row["commit_sha"] if row else None

    def base_set(self, project_uid: str, peer_install_id: str, commit_sha: str) -> None:
        with self._tx() as conn:
            conn.execute("INSERT INTO peer_bases (project_uid, peer_install_id, commit_sha, updated_at) VALUES (?,?,?,?)"
                         " ON CONFLICT(project_uid, peer_install_id) DO UPDATE SET commit_sha=excluded.commit_sha, updated_at=excluded.updated_at",
                         (project_uid, peer_install_id, commit_sha, time.time()))

    def base_clear(self, project_uid: str, peer_install_id: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM peer_bases WHERE project_uid=? AND peer_install_id=?", (project_uid, peer_install_id))


    def detached_set(self, project_uid: str, install_id: str, root: str) -> None:
        with self._tx() as conn:
            conn.execute("INSERT INTO detached_copies (project_uid, install_id, root, created_at) VALUES (?,?,?,?)"
                         " ON CONFLICT(project_uid, install_id) DO UPDATE SET root=excluded.root, created_at=excluded.created_at",
                         (project_uid, install_id, root, time.time()))

    def detached_get(self, project_uid: str, install_id: str) -> Optional[str]:
        with self._borrow() as conn:
            row = conn.execute("SELECT root FROM detached_copies WHERE project_uid=? AND install_id=?", (project_uid, install_id)).fetchone()
        return row["root"] if row else None

    def detached_delete(self, project_uid: str, install_id: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM detached_copies WHERE project_uid=? AND install_id=?", (project_uid, install_id))


    def agent_job_for_session(self, session_id: Optional[str], session_uuid: Optional[str] = None) -> Optional[HostJob]:
        keys = [(col, val) for col, val in (("worker_session_id", session_id), ("worker_session_uuid", session_uuid)) if val]
        if not keys:
            return None
        live = (HostState.PREPARING.value, HostState.RUNNING.value, HostState.PARKED.value)
        where = " OR ".join(f"{col}=?" for col, _ in keys)
        with self._borrow() as conn:
            row = conn.execute(f"SELECT * FROM host_jobs WHERE body='agent' AND state IN ({','.join('?' for _ in live)}) AND ({where}) "
                               "ORDER BY created_at DESC LIMIT 1", (*live, *[v for _, v in keys])).fetchone()
        return _host(row) if row else None


    def made_copy_put(self, root: str, **fields: Any) -> None:
        bad = set(fields) - _MADE_COPY_COLS
        if bad:
            raise TypeError(f"not a made_copies column: {sorted(bad)}")
        for flag in ("auto", "folder_made"):
            if flag in fields:
                fields[flag] = 1 if fields[flag] else 0
        with self._tx() as conn:
            conn.execute("INSERT OR IGNORE INTO made_copies (root) VALUES (?)", (root,))
            if fields:
                conn.execute(f"UPDATE made_copies SET {','.join(f'{c}=?' for c in fields)} WHERE root=?", [*fields.values(), root])

    def made_copy_get(self, root: str) -> Optional[Dict[str, Any]]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM made_copies WHERE root=?", (root,)).fetchone()
        return dict(row) if row else None

    def made_copy_delete(self, root: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM made_copies WHERE root=?", (root,))


    def needs_rows(self, project_uid: str) -> Dict[str, Tuple[List[str], List[str]]]:
        with self._borrow() as conn:
            rows = conn.execute("SELECT kind, needs_json, prefer_json FROM project_needs WHERE project_uid=?", (project_uid,)).fetchall()
        return {r["kind"]: ([str(w) for w in json.loads(r["needs_json"])], [str(w) for w in json.loads(r["prefer_json"])]) for r in rows}

    def needs_replace(self, project_uid: str, docs: Dict[str, Optional[Tuple[List[str], List[str]]]]) -> None:
        with self._tx() as conn:
            for kind, doc in docs.items():
                if doc is None:
                    conn.execute("DELETE FROM project_needs WHERE project_uid=? AND kind=?", (project_uid, kind))
                else:
                    conn.execute("INSERT INTO project_needs (project_uid, kind, needs_json, prefer_json, updated_at) VALUES (?,?,?,?,?)"
                                 " ON CONFLICT(project_uid, kind) DO UPDATE SET needs_json=excluded.needs_json, "
                                 "prefer_json=excluded.prefer_json, updated_at=excluded.updated_at",
                                 (project_uid, kind, json.dumps(doc[0]), json.dumps(doc[1]), time.time()))


    def marked_projects(self) -> List[str]:
        with self._borrow() as conn:
            return [r["project_uid"] for r in conn.execute("SELECT project_uid FROM project_policy WHERE auto_delegate=1 ORDER BY project_uid")]

    def delegate_marks(self) -> Tuple[Set[str], Dict[str, int]]:
        with self._borrow() as conn:
            marked = {r["project_uid"] for r in conn.execute("SELECT project_uid FROM project_policy WHERE auto_delegate=1")}
            made = {r["project_uid"]: int(r["n"]) for r in conn.execute("SELECT project_uid, COUNT(*) AS n FROM auto_replicas GROUP BY project_uid")}
        return marked, made

    def sync_get(self, project_uid: str, peer: str) -> Optional[dict]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM sync_state WHERE project_uid=? AND peer=?", (project_uid, peer)).fetchone()
        return dict(row) if row else None

    def sync_put(self, project_uid: str, peer: str, **cols: Any) -> None:
        bad = set(cols) - {"refs_digest", "warm_commit", "last_ok", "last_try", "fails"}
        if bad:
            raise TypeError(f"not a sync_state column: {sorted(bad)}")
        with self._tx() as conn:
            conn.execute("INSERT OR IGNORE INTO sync_state (project_uid, peer) VALUES (?,?)", (project_uid, peer))
            if cols:
                conn.execute(f"UPDATE sync_state SET {','.join(f'{c}=?' for c in cols)} WHERE project_uid=? AND peer=?", [*cols.values(), project_uid, peer])


    _INSTALL_COLS = ("id", "tool", "formula", "caller_install", "job_id", "state", "started_at", "ended_at", "exit_code", "tail")

    def install_put(self, row: InstallRow) -> InstallRow:
        with self._tx() as conn:
            conn.execute(f"INSERT INTO tool_installs ({','.join(self._INSTALL_COLS)}) VALUES ({','.join('?' for _ in self._INSTALL_COLS)})",
                         [getattr(row, c) for c in self._INSTALL_COLS])
        return row

    def install_get(self, install_id: str) -> Optional[InstallRow]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM tool_installs WHERE id=?", (install_id,)).fetchone()
        return InstallRow(**dict(row)) if row else None

    def install_update(self, install_id: str, **fields: Any) -> None:
        bad = set(fields) - (set(self._INSTALL_COLS) - {"id"})
        if bad:
            raise TypeError(f"not a tool_installs column: {sorted(bad)}")
        with self._tx() as conn:
            conn.execute(f"UPDATE tool_installs SET {','.join(f'{c}=?' for c in fields)} WHERE id=?", [*fields.values(), install_id])

    def install_list(self, limit: int = 50) -> List[InstallRow]:
        with self._borrow() as conn:
            rows = conn.execute("SELECT * FROM tool_installs ORDER BY started_at DESC, rowid DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [InstallRow(**dict(r)) for r in rows]

    def install_for_job(self, caller: str, job_id: str) -> List[InstallRow]:
        with self._borrow() as conn:
            rows = conn.execute("SELECT * FROM tool_installs WHERE caller_install=? AND job_id=? ORDER BY started_at", (caller, job_id)).fetchall()
        return [InstallRow(**dict(r)) for r in rows]

    def install_count_since(self, caller: str, since: float) -> int:
        with self._borrow() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM tool_installs WHERE caller_install=? AND started_at>=?", (caller, since)).fetchone()[0])

    def install_fail_open(self, now: float, why: str) -> int:
        with self._tx() as conn:
            return conn.execute("UPDATE tool_installs SET state='failed', ended_at=?, tail=? WHERE state IN ('queued','running')", (now, why)).rowcount


    def episode_add(self, day: str, project_uid: str, minutes: float, outcome: str, at: float) -> None:
        with self._tx() as conn:
            conn.execute("INSERT INTO heavy_episodes (day, project_uid, minutes, outcome, at) VALUES (?,?,?,?,?)",
                         (day, project_uid, float(minutes), outcome, float(at)))

    def episodes_since(self, cutoff: float) -> List[Tuple[str, float, str]]:
        with self._borrow() as conn:
            return [(r[0], r[1], r[2]) for r in conn.execute("SELECT project_uid, minutes, outcome FROM heavy_episodes WHERE at>=? ORDER BY id", (cutoff,))]

    def load_hours_put(self, rows: Sequence[Dict[str, Any]], *, keep_since_hour: int) -> None:
        with self._tx() as conn:
            for r in rows:
                conn.execute("INSERT OR REPLACE INTO load_hours (hour, busy_pct, pegged_minutes, max_run_queue_per_core, mem_warn_minutes) VALUES (?,?,?,?,?)",
                             (int(r["hour"]), r["busy_pct"], r["pegged_minutes"], r["max_run_queue_per_core"], r["mem_warn_minutes"]))
            conn.execute("DELETE FROM load_hours WHERE hour<?", (int(keep_since_hour),))
            conn.execute("DELETE FROM heavy_episodes WHERE at<?", (keep_since_hour * 3600.0,))

    def load_hours_since(self, hour: int) -> List[Dict[str, Any]]:
        with self._borrow() as conn:
            return [dict(r) for r in conn.execute("SELECT hour, busy_pct, pegged_minutes, max_run_queue_per_core, mem_warn_minutes "
                                                  "FROM load_hours WHERE hour>=? ORDER BY hour", (int(hour),))]

    def first_metric_at(self) -> Optional[float]:
        with self._borrow() as conn:
            first = [conn.execute("SELECT MIN(at) FROM heavy_episodes").fetchone()[0], conn.execute("SELECT MIN(hour) * 3600.0 FROM load_hours").fetchone()[0]]
        known = [v for v in first if v is not None]
        return min(known) if known else None

    def request_kinds_since(self, cutoff: float, project_uids: Sequence[str]) -> List[str]:
        if not project_uids:
            return []
        marks = ",".join("?" for _ in project_uids)
        with self._borrow() as conn:
            rows = conn.execute(f"SELECT request_json FROM jobs WHERE created_at>=? AND project_uid IN ({marks})", (cutoff, *project_uids)).fetchall()
        kinds: List[str] = []
        for (raw,) in rows:
            try:
                kinds.append(str(json.loads(raw).get("request", {}).get("kind", "")))
            except (ValueError, AttributeError):
                continue
        return kinds

    def remote_seconds_since(self, cutoff: float) -> float:
        with self._borrow() as conn:
            row = conn.execute("SELECT SUM(ended_at - started_at) FROM jobs WHERE peer_install_id IS NOT NULL AND started_at IS NOT NULL "
                               "AND ended_at IS NOT NULL AND ended_at>=?", (cutoff,)).fetchone()
        return float(row[0] or 0.0)


    def placement_put(self, request_id: str, **fields: Any) -> None:
        if set(fields) - _PLACEMENT_COLS:
            raise JobError("bad_request", "unknown placement column", 422)
        cols = ["request_id", "created_at", *fields]
        updates = ", ".join(f"{c}=excluded.{c}" for c in fields) or "request_id=request_id"
        with self._tx() as conn:
            conn.execute(f"INSERT INTO session_placements ({', '.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
                         f"ON CONFLICT(request_id) DO UPDATE SET {updates}", (request_id, time.time(), *fields.values()))

    def placement_get(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM session_placements WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def placement_list(self, project_uid: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._borrow() as conn:
            rows = conn.execute("SELECT * FROM session_placements WHERE project_uid=? ORDER BY created_at DESC LIMIT ?",
                                (project_uid, max(1, int(limit)))).fetchall()
        return [dict(r) for r in rows]

    def automation_placement_get(self, automation_id: str) -> Optional[str]:
        with self._borrow() as conn:
            row = conn.execute("SELECT placement FROM automation_placement WHERE automation_id=?", (automation_id,)).fetchone()
        return str(row["placement"]) if row else None

    def automation_placement_set(self, automation_id: str, placement: str) -> None:
        if placement not in ("here", "auto"):
            raise JobError("bad_request", "placement is here or auto", 422)
        with self._tx() as conn:
            conn.execute("INSERT INTO automation_placement (automation_id, placement, updated_at) VALUES (?,?,?) "
                         "ON CONFLICT(automation_id) DO UPDATE SET placement=excluded.placement, updated_at=excluded.updated_at",
                         (automation_id, placement, time.time()))

    def automation_placement_delete(self, automation_id: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM automation_placement WHERE automation_id=?", (automation_id,))


    def host_place_get(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM host_session_places WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def host_place_list(self) -> List[Dict[str, Any]]:
        with self._borrow() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM host_session_places").fetchall()]

    def host_place_put(self, request_id: str, **fields: Any) -> None:
        if set(fields) - _HOST_PLACE_COLS:
            raise JobError("bad_request", "unknown placement column", 422)
        cols = ["request_id", "created_at", *fields]
        updates = ", ".join(f"{c}=excluded.{c}" for c in fields) or "request_id=request_id"
        with self._tx() as conn:
            conn.execute(f"INSERT INTO host_session_places ({', '.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
                         f"ON CONFLICT(request_id) DO UPDATE SET {updates}", (request_id, time.time(), *fields.values()))

    def ssh_target_get(self, host_key: str) -> Optional[Dict[str, Any]]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM ssh_targets WHERE host_key=?", (host_key,)).fetchone()
        return dict(row) if row else None

    def ssh_target_put(self, host_key: str, **fields: Any) -> None:
        bad = set(fields) - _SSH_TARGET_COLS
        if bad:
            raise TypeError(f"not an ssh_targets column: {sorted(bad)}")
        fields["updated_at"] = time.time()
        with self._tx() as conn:
            conn.execute("INSERT OR IGNORE INTO ssh_targets (host_key) VALUES (?)", (host_key,))
            conn.execute(f"UPDATE ssh_targets SET {','.join(f'{c}=?' for c in fields)} WHERE host_key=?", [*fields.values(), host_key])

    def ssh_target_drop(self, host_key: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM ssh_targets WHERE host_key=?", (host_key,))
            conn.execute("DELETE FROM ssh_seeds WHERE host_key=?", (host_key,))

    def ssh_targets_all(self) -> List[Dict[str, Any]]:
        with self._borrow() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM ssh_targets ORDER BY host_key")]

    def ssh_seed_get(self, project_uid: str, host_key: str) -> Optional[Dict[str, Any]]:
        with self._borrow() as conn:
            row = conn.execute("SELECT * FROM ssh_seeds WHERE project_uid=? AND host_key=?", (project_uid, host_key)).fetchone()
        return dict(row) if row else None

    def ssh_seeds_for(self, host_key: str) -> List[str]:
        with self._borrow() as conn:
            return [r["project_uid"] for r in conn.execute("SELECT project_uid FROM ssh_seeds WHERE host_key=? ORDER BY project_uid", (host_key,))]

    def ssh_seed_drop(self, project_uid: str, host_key: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM ssh_seeds WHERE project_uid=? AND host_key=?", (project_uid, host_key))

    def ssh_seed_set(self, project_uid: str, host_key: str, head: str) -> None:
        with self._tx() as conn:
            conn.execute("INSERT INTO ssh_seeds (project_uid, host_key, head, seeded_at) VALUES (?,?,?,?)"
                         " ON CONFLICT(project_uid, host_key) DO UPDATE SET head=excluded.head, seeded_at=excluded.seeded_at",
                         (project_uid, host_key, head, time.time()))
