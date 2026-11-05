
from __future__ import annotations

import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import structlog

logger = structlog.get_logger(__name__)

LEASE_DIR_ENV = "CARNIVORE_TESTSRV_LEASE_DIR"
OWNER_PID_ENV = "CARNIVORE_OWNER_PID"
TTL_ENV = "CARNIVORE_DEV_LEASE_TTL_S"
DEFAULT_TTL_S = 300.0
LEASE_MAX_S = 3600


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lease_gone(lease_dir: Path) -> bool:
    if not lease_dir.is_dir():
        return True
    try:
        rec = json.loads((lease_dir / "holder").read_text())
        pid, at = rec.get("pid"), float(rec["at"])
    except (OSError, ValueError, KeyError, TypeError):
        try:
            pid, at = None, lease_dir.stat().st_mtime
        except OSError:
            return True
    if isinstance(pid, int) and pid > 0 and not _pid_alive(pid):
        return True
    return time.time() - at > LEASE_MAX_S


def _in_dev_worktree(repo: Path) -> bool:
    root = Path(os.path.expanduser("~/dev-worktrees")).resolve()
    return root in repo.resolve().parents


def make_owner_check(repo: Path, environ=os.environ) -> Optional[Callable[[], bool]]:
    lease = environ.get(LEASE_DIR_ENV)
    if lease:
        lease_dir = Path(lease)
        return lambda: lease_gone(lease_dir)
    if not _in_dev_worktree(repo):
        return None
    raw = environ.get(OWNER_PID_ENV)
    if raw and raw.isdigit() and int(raw) > 1:
        owner = int(raw)
        return lambda: not _pid_alive(owner)
    parent = os.getppid()
    if parent <= 1:
        return None
    return lambda: os.getppid() != parent or not _pid_alive(parent)


def start_watch(repo: Optional[Path] = None, environ=os.environ,
                on_expire: Callable[[], None] = lambda: os.kill(os.getpid(), signal.SIGTERM)) -> Optional[threading.Thread]:
    check = make_owner_check(repo or Path(__file__).resolve().parents[2], environ)
    if check is None:
        return None
    try:
        ttl = max(float(environ.get(TTL_ENV, DEFAULT_TTL_S)), 0.5)
    except ValueError:
        ttl = DEFAULT_TTL_S
    step = min(30.0, ttl / 4)

    def run() -> None:
        gone_since: Optional[float] = None
        while True:
            time.sleep(step)
            if not check():
                gone_since = None
                continue
            gone_since = gone_since or time.monotonic()
            if time.monotonic() - gone_since >= ttl:
                logger.warning("dev_server_owner_gone_exiting", ttl_s=ttl)
                on_expire()
                return

    t = threading.Thread(target=run, name="dev-lease-watch", daemon=True)
    t.start()
    return t
