
from __future__ import annotations

import logging
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from src.core.product_identity import BUNDLE_ID, MENUBAR_STATE_DIR_NAME, PRODUCT_NAME

log = logging.getLogger(__name__)

ENGINE_COMMAND_MARKER = " -m src.main"
PORT_RELEASE_TIMEOUT_S = 15.0
POLL_STEP_S = 0.5
APP_QUIT_TIMEOUT_S = 10.0
SUBPROCESS_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 1.0
UNMEASURED_RC = 124
PORT_MIN, PORT_MAX = 1, 65535

RunFn = Callable[..., "subprocess.CompletedProcess[str]"]
KillFn = Callable[[int, int], None]
SleepFn = Callable[[float], None]
ConnectFn = Callable[[int], bool]


class RestartError(Exception):
    pass


class UnmeasuredError(RestartError):
    pass


@dataclass
class RestartOutcome:

    app_was_running: bool = False
    app_quit: bool = False
    stopped_pids: List[int] = field(default_factory=list)
    port_free: bool = False
    reopened: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def restarted(self) -> bool:
        return self.port_free and (self.app_quit or not self.app_was_running)


def engine_dir() -> Path:
    override = os.environ.get("CARNIVORE_ENGINE_DIR")
    if override:
        return Path(override)
    return Path.home() / "Library" / "Application Support" / MENUBAR_STATE_DIR_NAME / "server"


def is_installed_engine_root(project_root: Path) -> bool:
    return os.path.realpath(project_root) == os.path.realpath(engine_dir())


def engine_owns_port(port: int, run: Optional[RunFn] = None) -> bool:
    try:
        pids = listener_pids(port, run)
    except UnmeasuredError:
        return False
    if not pids:
        return False
    return all(holder_check(pid, run)[0] == OURS for pid in pids)


def parse_port(text: Optional[str], default: int) -> int:
    if text is None or not text.strip().isdigit():
        return default
    value = int(text.strip())
    return value if PORT_MIN <= value <= PORT_MAX else default


def _out(run: Optional[RunFn], argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    runner = run if run is not None else subprocess.run
    try:
        return runner(list(argv), capture_output=True, text=True, check=False, timeout=SUBPROCESS_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("app_restart.call_unmeasured tool=%s error=%s", argv[0], type(exc).__name__)
        return subprocess.CompletedProcess(list(argv), UNMEASURED_RC, stdout="", stderr="")


def app_is_running(run: Optional[RunFn] = None, name: str = PRODUCT_NAME, uid: Optional[int] = None) -> bool:
    want = os.getuid() if uid is None else uid
    return _out(run, ["pgrep", "-u", str(want), "-x", name]).returncode == 0


def listener_pids(port: int, run: Optional[RunFn] = None) -> List[int]:
    done = _out(run, ["lsof", "-b", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"])
    if done.returncode not in (0, 1):
        raise UnmeasuredError(f"lsof could not measure port {port} (rc {done.returncode})")
    return [int(tok) for tok in done.stdout.split() if tok.isdigit()]


def port_accepts(port: int) -> bool:
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S):
                return True
        except OSError:
            continue
    return False


def _ps_field(run: Optional[RunFn], pid: int, column: str) -> str:
    return _out(run, ["ps", "-p", str(pid), "-o", f"{column}="]).stdout.strip()


def _cwd_of(run: Optional[RunFn], pid: int) -> str:
    done = _out(run, ["lsof", "-b", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    names = [ln[1:] for ln in done.stdout.splitlines() if ln.startswith("n")]
    return names[0] if names else ""


OURS, FOREIGN, GONE = "ours", "foreign", "gone"


def holder_check(pid: int, run: Optional[RunFn] = None, uid: Optional[int] = None,
                 server_dir: Optional[Path] = None) -> Tuple[str, str]:
    want = os.getuid() if uid is None else uid
    command = _ps_field(run, pid, "command")
    if not command:
        return GONE, ""
    owner = _ps_field(run, pid, "uid")
    cwd = _cwd_of(run, pid)
    start = _ps_field(run, pid, "lstart")
    stat = _ps_field(run, pid, "stat")
    if not stat or stat.startswith("Z"):
        return GONE, ""
    expected = os.path.realpath(server_dir if server_dir is not None else engine_dir())
    is_ours = (ENGINE_COMMAND_MARKER in command and owner == str(want)
               and bool(cwd) and cwd == expected and bool(start))
    return (OURS, start) if is_ours else (FOREIGN, start)


def _wait_until(done: Callable[[], bool], timeout_s: float, sleep: SleepFn) -> bool:
    waited = 0.0
    while not done():
        if waited >= timeout_s:
            return False
        sleep(POLL_STEP_S)
        waited += POLL_STEP_S
    return True


def _port_is_free(port: int, run: Optional[RunFn], connect: Optional[ConnectFn]) -> bool:
    probe = connect if connect is not None else port_accepts
    return not listener_pids(port, run) and not probe(port)


def _judge_listeners(port: int, outcome: RestartOutcome, run: Optional[RunFn],
                     connect: Optional[ConnectFn]) -> Optional[List[Tuple[int, str]]]:
    ours: List[Tuple[int, str]] = []
    for pid in listener_pids(port, run):
        verdict, start = holder_check(pid, run)
        if verdict == FOREIGN:
            outcome.notes.append(f"port {port} is held by pid {pid}, not a Carnivore engine; nothing was stopped")
            return None
        if verdict == OURS:
            ours.append((pid, start))
    probe = connect if connect is not None else port_accepts
    if not ours and probe(port):
        outcome.notes.append(f"port {port} accepts connections but no process of ours holds it; nothing was stopped")
        return None
    return ours


def stop_engine(port: int, outcome: RestartOutcome, run: Optional[RunFn] = None,
                kill: Optional[KillFn] = None, sleep: Optional[SleepFn] = None,
                connect: Optional[ConnectFn] = None) -> None:
    do_kill = kill if kill is not None else os.kill
    do_sleep = sleep if sleep is not None else time.sleep
    try:
        targets = _judge_listeners(port, outcome, run, connect)
        if targets is None:
            return
        for pid, start in targets:
            verdict, again = holder_check(pid, run)
            if verdict == GONE:
                continue
            if verdict != OURS or again != start:
                outcome.notes.append(f"pid {pid} changed identity before the signal; nothing more was stopped")
                return
            do_kill(pid, signal.SIGTERM)
            outcome.stopped_pids.append(pid)
        outcome.port_free = _wait_until(lambda: _port_is_free(port, run, connect), PORT_RELEASE_TIMEOUT_S, do_sleep)
    except UnmeasuredError as exc:
        outcome.notes.append(f"{exc}; nothing was stopped")
        return
    if not outcome.port_free:
        outcome.notes.append(f"port {port} is still held after {PORT_RELEASE_TIMEOUT_S:.0f}s")


def _quit_app(outcome: RestartOutcome, run: Optional[RunFn], sleep: SleepFn, name: str) -> None:
    asked = _out(run, ["osascript", "-e", f'tell application id "{BUNDLE_ID}" to quit'])
    if asked.returncode == 0:
        outcome.app_quit = _wait_until(lambda: not app_is_running(run, name), APP_QUIT_TIMEOUT_S, sleep)
    if not outcome.app_quit:
        outcome.notes.append(f"{name} did not quit (macOS refused the request or it timed out)")


def restart_app_and_engine(port: int, run: Optional[RunFn] = None, kill: Optional[KillFn] = None,
                           sleep: Optional[SleepFn] = None, name: str = PRODUCT_NAME,
                           connect: Optional[ConnectFn] = None) -> RestartOutcome:
    if not PORT_MIN <= port <= PORT_MAX:
        raise ValueError(f"port {port} is outside {PORT_MIN} to {PORT_MAX}")
    do_sleep = sleep if sleep is not None else time.sleep
    outcome = RestartOutcome(app_was_running=app_is_running(run, name))
    if outcome.app_was_running:
        _quit_app(outcome, run, do_sleep, name)
        if not outcome.app_quit:
            return outcome
    stop_engine(port, outcome, run, kill, do_sleep, connect)
    if outcome.app_was_running and outcome.port_free:
        outcome.reopened = _out(run, ["open", "-b", BUNDLE_ID]).returncode == 0
    return outcome
