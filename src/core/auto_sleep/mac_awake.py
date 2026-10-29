
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional, Protocol

import structlog

logger = structlog.get_logger()

CAFFEINATE_PATH = "/usr/bin/caffeinate"


class _Popen(Protocol):

    pid: int

    def poll(self) -> Optional[int]: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: Optional[float] = None) -> int: ...


ProcessLauncher = Callable[[List[str]], _Popen]


def _default_launcher(args: List[str]) -> _Popen:
    return subprocess.Popen(  # noqa: S603
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class MacAwakeGuard:

    def __init__(
        self,
        *,
        server_pid: Optional[int] = None,
        launcher: ProcessLauncher = _default_launcher,
        caffeinate_path: str = CAFFEINATE_PATH,
    ) -> None:
        self._server_pid = server_pid if server_pid is not None else os.getpid()
        self._launcher = launcher
        self._caffeinate_path = caffeinate_path
        self._proc: Optional[_Popen] = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        proc = self._proc
        if proc is None:
            return False
        if proc.poll() is not None:
            logger.warning("mac_awake_child_died", pid=proc.pid)
            self._proc = None
            return False
        return True

    def reconcile(self, keep_awake_count: int) -> None:
        with self._lock:
            want = keep_awake_count > 0
            if want and not self.active:
                self._start()
            elif not want and self.active:
                self._stop()

    def _start(self) -> None:
        if not Path(self._caffeinate_path).exists():
            logger.warning("mac_awake_caffeinate_missing", path=self._caffeinate_path)
            return
        args = [self._caffeinate_path, "-i", "-w", str(self._server_pid)]
        try:
            proc = self._launcher(args)
        except OSError as exc:
            logger.warning("mac_awake_start_failed", error=type(exc).__name__)
            return
        self._proc = proc
        logger.info("mac_awake_started", pid=proc.pid, server_pid=self._server_pid)

    def _stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception as exc:
            logger.warning("mac_awake_stop_failed", pid=proc.pid, error=type(exc).__name__)
        else:
            logger.info("mac_awake_stopped", pid=proc.pid)


def reconcile_at_boot(guard: MacAwakeGuard, config_path: Path) -> None:
    from src.core.auto_sleep import store

    try:
        config = store.read(config_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.info("mac_awake_boot_no_config", error=type(exc).__name__)
        guard.reconcile(0)
        return
    guard.reconcile(config.mac_awake_demand())
