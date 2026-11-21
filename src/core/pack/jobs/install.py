
from __future__ import annotations

import asyncio
import getpass
import os
import secrets
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.pack.jobs.types import JobError
from src.core.pack.machines import restrictions as restrictions_mod

log = structlog.get_logger(__name__)

CAP_INSTALL = "pack.jobs.install"
ALLOW: Dict[str, str] = {"ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "node": "node", "npm": "node", "gh": "gh", "python3.12": "python@3.12"}
BREW_PATHS = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
FIXED_PATH = "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
BREW_FLAGS = {"HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ANALYTICS": "1", "HOMEBREW_NO_ENV_HINTS": "1", "HOMEBREW_NO_INSTALL_CLEANUP": "1",
              "HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK": "1", "HOMEBREW_NO_INSTALL_UPGRADE": "1", "NONINTERACTIVE": "1"}
TIMEOUT_S = 1200.0
PER_DAY = 5
MAX_TOOLS = 6
TAIL_CHARS = 300
QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
DONE_STATES = (DONE, FAILED)

RunProc = Callable[[List[str], Dict[str, str], Path, float], Tuple[int, str]]


@dataclass
class InstallRow:

    id: str
    tool: str
    formula: str
    caller_install: str = ""
    job_id: str = ""
    state: str = QUEUED
    started_at: float = 0.0
    ended_at: Optional[float] = None
    exit_code: Optional[int] = None
    tail: str = ""

    def public(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if k != "formula"}


def formulas_of(tools: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(ALLOW[t] for t in tools))


def covered(tools: Sequence[str]) -> List[str]:
    made = set(formulas_of(tools))
    return [name for name, formula in ALLOW.items() if formula in made]


def _tool_present(name: str) -> bool:
    from src.core.pack.machines import probe

    return probe.tool_present(name)


def find_brew() -> Optional[str]:
    for path in BREW_PATHS:
        try:
            if os.path.isfile(path) and os.access(path, os.X_OK) and os.stat(path).st_uid == os.getuid():
                return path
        except OSError:
            continue
    return None


def brew_env() -> Dict[str, str]:
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = ""
    return {"HOME": os.path.expanduser("~"), **({"USER": user} if user else {}), "LANG": "en_US.UTF-8", "PATH": FIXED_PATH, **BREW_FLAGS}


def clean_text(text: object) -> str:
    return "".join(c for c in str(text or "") if c.isprintable())[:TAIL_CHARS]


def _tail(path: Path) -> str:
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return ""
    return clean_text(lines[-1]) if lines else ""


def run_brew(argv: List[str], env: Dict[str, str], log_path: Path, timeout: float) -> Tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=fd, stderr=subprocess.STDOUT, env=env, start_new_session=True)  # noqa: S603
    finally:
        os.close(fd)
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
        return 124, "timed out and was stopped"
    return code, _tail(log_path)


class Installer:

    def __init__(self, store: Any, jobs_root: Path, *, brew: Callable[[], Optional[str]] = find_brew,
                 restrictions: Callable[[], restrictions_mod.Restrictions], run_proc: RunProc = run_brew,
                 clock: Callable[[], float] = time.time, owns_job: Callable[[str, str], bool] = lambda _job, _caller: True,
                 present: Optional[Callable[[str], bool]] = None,
                 on_installing: Callable[[Optional[str]], None] = lambda _tool: None, on_done: Callable[[], None] = lambda: None) -> None:
        self._store, self._root, self._brew, self._restrictions, self._run_proc, self._clock = store, Path(jobs_root), brew, restrictions, run_proc, clock
        self._owns_job, self._on_installing, self._on_done = owns_job, on_installing, on_done
        self._present = present or _tool_present
        self._one = asyncio.Lock()
        self._queueing = threading.Lock()
        self._tasks: set = set()

    def _check(self, tools: Sequence[str]) -> List[str]:
        if not tools or len(tools) > MAX_TOOLS or not all(isinstance(t, str) and t in ALLOW for t in tools):
            raise JobError("tool_not_allowed", "only ffmpeg, ffprobe, node, npm, gh and python3.12 can be installed", 422)
        rule = restrictions_mod.check(self._restrictions(), restrictions_mod.ACTION_INSTALL_TOOLS)
        if rule:
            raise JobError("pack_restricted", f"this computer's own restriction {rule} refuses installs", 403)
        if self._brew() is None:
            raise JobError("no_brew", "homebrew is not installed on this computer", 409)
        have = [t for t in tools if self._present(t)]
        if have:
            raise JobError("already_present", f"this computer already has {', '.join(dict.fromkeys(have))}", 409)
        return formulas_of(tools)

    def _queue(self, caller: str, job_id: str, tools: Sequence[str]) -> List[InstallRow]:
        with self._queueing:
            return self._queue_locked(caller, job_id, tools)

    def _queue_locked(self, caller: str, job_id: str, tools: Sequence[str]) -> List[InstallRow]:
        now = self._clock()
        new = [f for f in formulas_of(tools) if not (job_id and any(r.formula == f and r.state != FAILED for r in self._store.install_for_job(caller, job_id)))]
        if self._store.install_count_since(caller, now - 86400.0) + len(new) > PER_DAY:
            raise JobError("install_limit", f"{PER_DAY} installs a day is the most one computer may ask of this one", 429)
        rows: List[InstallRow] = []
        for formula in formulas_of(tools):
            tool = next(t for t in tools if ALLOW[t] == formula)
            same = [r for r in self._store.install_for_job(caller, job_id) if r.formula == formula and r.state != FAILED] if job_id else []
            if same:
                rows.append(same[0])
                continue
            rows.append(self._store.install_put(InstallRow(id="ins_" + secrets.token_hex(6), tool=tool, formula=formula, caller_install=caller,
                                                           job_id=job_id, started_at=now)))
        return rows

    async def request(self, caller: str, job_id: str, tools: List[str], *, owner: bool = False) -> List[InstallRow]:
        self._check(tools)
        if not owner and not await asyncio.to_thread(self._owns_job, job_id, caller):
            raise JobError("unknown_job", "no such job", 404)
        rows = await asyncio.to_thread(self._queue, caller, job_id, tools)
        fresh = [r for r in rows if r.state == QUEUED]
        if fresh:
            task = asyncio.get_running_loop().create_task(self._drain([r.id for r in fresh]))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return rows

    async def _drain(self, ids: List[str]) -> None:
        async with self._one:
            ran = False
            for row_id in ids:
                try:
                    ran = await asyncio.to_thread(self._run_one, row_id) or ran
                except Exception as exc:  # noqa: BLE001
                    log.warning("pack_install_crashed", install_id=row_id, error=type(exc).__name__)
                    self._store.install_update(row_id, state=FAILED, ended_at=self._clock(), tail=f"the install failed ({type(exc).__name__})")
            self._on_installing(None)
            if ran:
                try:
                    await asyncio.to_thread(self._on_done)
                except Exception as exc:  # noqa: BLE001
                    log.warning("pack_install_reprobe_failed", error=type(exc).__name__)

    def _run_one(self, row_id: str) -> bool:
        row = self._store.install_get(row_id)
        if row is None or row.state != QUEUED:
            return False
        if restrictions_mod.check(self._restrictions(), restrictions_mod.ACTION_INSTALL_TOOLS):
            self._store.install_update(row_id, state=FAILED, ended_at=self._clock(), tail="this computer stopped allowing installs")
            return False
        brew = self._brew()
        if brew is None:
            self._store.install_update(row_id, state=FAILED, ended_at=self._clock(), tail="homebrew is not installed on this computer")
            return False
        self._store.install_update(row_id, state=RUNNING, started_at=self._clock())
        try:
            self._on_installing(row.tool)
        except ValueError:
            pass
        argv = [brew, "install", "--formula", row.formula]
        try:
            code, tail = self._run_proc(argv, brew_env(), self._root / "installs" / f"{row_id}.log", TIMEOUT_S)
        except OSError as exc:
            self._store.install_update(row_id, state=FAILED, ended_at=self._clock(), tail=f"homebrew could not start ({type(exc).__name__})")
            return False
        self._store.install_update(row_id, state=DONE if code == 0 else FAILED, ended_at=self._clock(), exit_code=code, tail=clean_text(tail))
        log.info("pack_install_finished", tool=row.tool, exit_code=code)
        return True

    def status(self, caller: str, install_id: str) -> InstallRow:
        row = self._store.install_get(install_id)
        if row is None or row.caller_install != caller:
            raise JobError("unknown_install", "no such install", 404)
        return row

    def rows(self, limit: int = 50) -> List[InstallRow]:
        return self._store.install_list(limit)

    def can_install(self) -> bool:
        return restrictions_mod.check(self._restrictions(), restrictions_mod.ACTION_INSTALL_TOOLS) is None and self._brew() is not None

    def recover(self) -> int:
        return self._store.install_fail_open(self._clock(), "a restart ended the install")
