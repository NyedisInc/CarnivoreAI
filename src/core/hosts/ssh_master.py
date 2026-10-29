"""One supervised OpenSSH ControlMaster: the connection a remote host rides.

Issue #162, slice S2. Rules and measurements: ``docs/remote-hosts-ssh.md``.
The channel pool over one or more of these is :mod:`src.core.hosts.ssh_pool`.

THE SERVER OWNS THE MASTER'S LIFE. The master is a foreground ``ssh -N``
child with ``ControlPersist=no``, so it lives exactly as long as the process
this module watches, and a dead master is observed as an EXIT, not guessed
at. ``UP`` is measured: the socket file exists AND ``ssh -O check`` names
this master's own pid. Once up, ``-O check`` runs every ``check_interval``
seconds so a master whose socket vanished is replaced rather than trusted.

THE STATE MACHINE::

    DISCONNECTED --connect()--> CONNECTING --ready--> UP
    CONNECTING or UP --a retryable failure--> RETRYING --backoff--> CONNECTING
    CONNECTING or UP --a parked failure--> REFUSED   (connect() leaves it)
    any --disconnect()--> DISCONNECTED

A RETRYING master waits 1, 2, 4 ... 60 s (jittered down to half) between
attempts, and the count resets once a master has stayed up
``stable_after`` seconds, so a flapping link cannot hammer the far box.
PARKED failures are the ones waiting cannot fix: a changed or unverifiable
host key is a security event the user has to look at (decision D4), a
refused login needs the user's key or agent (and retrying could raise an
agent approval dialog every minute), a missing ssh binary needs an install.

THE CONTROL PATH IS OURS ALONE. It lives in a 0700 directory this user owns
(``~/.carnivore/cm`` by default) and is named ``<host>-<instance>-<slot>``,
where ``instance`` is a hash of this server's state directory, so the live
app and a test server on the same Mac never share, and never kill, each
other's masters. Before a master starts, a socket already on its path is
either a master left by an earlier run of THIS server (it is sent
``-O exit``) or a stale file from a SIGKILLed one (it is unlinked):
measured, OpenSSH will not bind over an existing socket and silently runs
unmultiplexed instead ("ControlSocket ... already exists, disabling
multiplexing").
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import random
import re
import signal
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

import structlog

from src.core.hosts import ssh_exec, ssh_forward
from src.core.hosts.ssh_exec import (
    FAILURE_AUTH,
    FAILURE_HOST_KEY_CHANGED,
    FAILURE_HOST_KEY_UNVERIFIED,
    FAILURE_SSH,
    FAILURE_SSH_UNAVAILABLE,
    FAILURE_TIMEOUT,
    SSH_BINARY,
    SshDestination,
    control_argv,
    failure_detail,
    master_argv,
    signal_group,
)
from src.core.test_write_guard import assert_test_write_allowed

logger = structlog.get_logger()

DISCONNECTED = "disconnected"
CONNECTING = "connecting"
UP = "up"
RETRYING = "retrying"
REFUSED = "refused"

FAILURE_MASTER_EXITED = "master_exited"
FAILURE_CONTROL_PATH_BUSY = "control_path_busy"

PARKED_FAILURES = frozenset(
    {FAILURE_HOST_KEY_CHANGED, FAILURE_HOST_KEY_UNVERIFIED, FAILURE_AUTH, FAILURE_SSH_UNAVAILABLE}
)

BACKOFF_CAP_SECONDS = 60.0

HOST_KEY_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
LOCAL_HOST_KEY = "local"

_CHECK_PID_RE = re.compile(r"Master running \(pid=(\d+)\)")


class SshTransportError(Exception):
    pass


def backoff_delay(attempt: int, rand: Callable[[], float] = random.random) -> float:
    nominal = min(BACKOFF_CAP_SECONDS, 2.0 ** min(max(attempt, 0), 6))
    return nominal * (0.5 + rand() / 2.0)


def default_control_dir() -> Path:
    return Path.home() / ".carnivore" / "cm"


def instance_tag_for(state_dir: str) -> str:
    """Eight hex characters that tell one server instance's sockets apart.

    Inputs: state_dir (str) - the server's state directory.
    Output: str - e.g. "dc491ea8".
    """
    return hashlib.sha256(state_dir.encode("utf-8")).hexdigest()[:8]


def default_instance_tag() -> str:
    """This server's instance tag, from its configured state directory.

    Output: str - :func:`instance_tag_for` of ``settings.get_state_dir()``.
    """
    from src.config import settings

    return instance_tag_for(str(settings.get_state_dir()))


def control_path_for(control_dir: Path, host_key: str, instance_tag: str, slot: int) -> str:
    """The control socket path of one slot of one host.

    Inputs: control_dir (Path); host_key (str) - the host's slug, never
      ``local``; instance_tag (str) - 8 hex; slot (int) - 0 to 99.
    Output: str - e.g. "/Users/a/.carnivore/cm/hosta-1a2b3c4d-0".
    Raises: SshTransportError - a bad key, tag or slot;
      ssh_exec.SshArgumentError - a path ssh could not use.
    """
    if HOST_KEY_RE.fullmatch(host_key or "") is None or host_key == LOCAL_HOST_KEY:
        raise SshTransportError(f"host key {host_key!r} cannot have an ssh master")
    if re.fullmatch(r"[0-9a-f]{8}", instance_tag or "") is None:
        raise SshTransportError(f"instance tag {instance_tag!r} is not 8 hex characters")
    if not 0 <= slot <= 99:
        raise SshTransportError(f"slot {slot} is out of range")
    return ssh_exec.validate_control_path(f"{control_dir}/{host_key}-{instance_tag}-{slot}")


def ensure_control_dir(control_dir: Path) -> Path:
    assert_test_write_allowed(control_dir)
    control_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(control_dir)
    if not stat.S_ISDIR(info.st_mode):
        raise SshTransportError(f"{control_dir} is not a real directory (a link or a file)")
    if info.st_uid != os.getuid():
        raise SshTransportError(f"{control_dir} is owned by another user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(control_dir, 0o700)
    return control_dir


@dataclass(frozen=True)
class MasterStatus:

    host_key: str
    slot: int
    state: str
    failure: Optional[str]
    detail: str
    pid: Optional[int]
    retry_in: Optional[float]


class SshMaster:

    def __init__(self, host_key: str, dest: SshDestination, control_path: str, *,
                 slot: int = 0, ssh_binary: str = SSH_BINARY, connect_timeout: float = 30.0,
                 check_interval: float = 30.0, stable_after: float = 30.0,
                 delay: Callable[[int], float] = backoff_delay,
                 on_change: Optional[Callable[[MasterStatus], None]] = None) -> None:
        self.host_key = host_key
        self.dest = dest
        self.slot = slot
        self.control_path = ssh_exec.validate_control_path(control_path)
        self._ssh_binary = ssh_binary
        self._connect_timeout = connect_timeout
        self._check_interval = check_interval
        self._stable_after = stable_after
        self._delay = delay
        self._on_change = on_change
        self._wanted = False
        self._task: Optional[asyncio.Task[None]] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._wake = asyncio.Event()
        self._changed = asyncio.Event()
        self._status = MasterStatus(host_key, slot, DISCONNECTED, None, "", None, None)
        self._attempts = 0


    @property
    def status(self) -> MasterStatus:
        return self._status

    @property
    def is_up(self) -> bool:
        proc = self._proc
        return self._status.state == UP and proc is not None and proc.returncode is None

    async def connect(self, *, wait: bool = True) -> MasterStatus:
        self._wanted = True
        if self._status.state not in (UP, CONNECTING):
            self._set(CONNECTING)
            if self._task is None or self._task.done():
                self._attempts = 0
                self._task = asyncio.create_task(
                    self._supervise(), name=f"ssh-master-{self.host_key}-{self.slot}")
            else:
                self._wake.set()
        if wait:
            while self._status.state == CONNECTING:
                await self._changed.wait()
        return self._status

    async def disconnect(self) -> None:
        self._wanted = False
        self._wake.set()
        if self._proc is not None:
            signal_group(self._proc, signal.SIGTERM)
        task, self._task = self._task, None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._set(DISCONNECTED)


    async def forward_local(self, local_path: str, host: str, port: int) -> str:
        self._require_up()
        return await ssh_forward.forward_local(self.dest, self.control_path, local_path, host, port,
                                               ssh_binary=self._ssh_binary)

    async def forward_local_unix(self, local_path: str, remote_path: str) -> str:
        self._require_up()
        return await ssh_forward.forward_local_unix(self.dest, self.control_path, local_path, remote_path,
                                                    ssh_binary=self._ssh_binary)

    async def forward_remote(self, remote_path: Optional[str], local_path: str):
        self._require_up()
        if remote_path is None:
            return await ssh_forward.forward_remote_tcp(self.dest, self.control_path, local_path,
                                                        ssh_binary=self._ssh_binary)
        return await ssh_forward.forward_remote_unix(self.dest, self.control_path, remote_path, local_path,
                                                     ssh_binary=self._ssh_binary)

    def _require_up(self) -> None:
        if not self.is_up:
            raise SshTransportError(f"the master for {self.host_key} is not up")

    async def check(self) -> bool:
        proc = self._proc
        return proc is not None and proc.returncode is None and await self._check_pid() == proc.pid


    def _set(self, state: str, failure: Optional[str] = None, detail: str = "",
             pid: Optional[int] = None, retry_in: Optional[float] = None) -> None:
        if (state, failure, detail, pid, retry_in) == (self._status.state, self._status.failure,
                                                       self._status.detail, self._status.pid,
                                                       self._status.retry_in):
            return
        self._status = MasterStatus(self.host_key, self.slot, state, failure, detail, pid, retry_in)
        log = logger.warning if failure else logger.info
        log("ssh_master_state", host=self.host_key, slot=self.slot, state=state,
            failure=failure, detail=detail[:200], retry_in=retry_in)
        self._changed.set()
        self._changed = asyncio.Event()
        if self._on_change is not None:
            try:
                self._on_change(self._status)
            except Exception:  # noqa: BLE001
                logger.exception("ssh_master_on_change_failed", host=self.host_key, slot=self.slot)

    async def _supervise(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while self._wanted:
                self._wake.clear()
                self._set(CONNECTING)
                failure, detail, up_for = await self._attempt(loop)
                if not self._wanted:
                    break
                if up_for is not None and up_for >= self._stable_after:
                    self._attempts = 0
                if failure in PARKED_FAILURES:
                    self._set(REFUSED, failure, detail)
                    return
                delay = self._delay(self._attempts)
                self._attempts += 1
                self._set(RETRYING, failure, detail, retry_in=round(delay, 1))
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("ssh_master_supervisor_failed", host=self.host_key, slot=self.slot)
            self._set(REFUSED, FAILURE_SSH, f"the ssh supervisor failed ({type(exc).__name__})")
        finally:
            await self._stop_process()

    async def _attempt(self, loop: asyncio.AbstractEventLoop
                       ) -> Tuple[Optional[str], str, Optional[float]]:
        await self._clear_control_path()
        try:
            proc = await asyncio.create_subprocess_exec(
                *master_argv(self.dest, self.control_path, ssh_binary=self._ssh_binary),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE, start_new_session=True)
        except OSError as exc:
            return FAILURE_SSH_UNAVAILABLE, failure_detail(FAILURE_SSH_UNAVAILABLE, str(exc)), None
        self._proc = proc
        stderr = bytearray()
        drain = asyncio.create_task(self._drain(proc, stderr))
        exited = asyncio.create_task(proc.wait())
        try:
            failure, detail = await self._wait_ready(loop, proc, exited, drain, stderr)
            if failure is not None or not self._wanted:
                return failure, detail, None
            up_at = loop.time()
            self._set(UP, pid=proc.pid)
            failure, detail = await self._watch(proc, exited, drain, stderr)
            return failure, detail, loop.time() - up_at
        finally:
            await self._stop_process()
            exited.cancel()
            drain.cancel()

    async def _wait_ready(self, loop: asyncio.AbstractEventLoop, proc: asyncio.subprocess.Process,
                          exited: "asyncio.Task[int]", drain: "asyncio.Task[None]",
                          stderr: bytearray) -> Tuple[Optional[str], str]:
        deadline = loop.time() + self._connect_timeout
        while self._wanted:
            if exited.done():
                return await self._exit_failure(proc, drain, stderr)
            if os.path.lexists(self.control_path):
                pid = await self._check_pid()
                if pid == proc.pid:
                    return None, ""
                if pid is not None:
                    return FAILURE_CONTROL_PATH_BUSY, (
                        f"another ssh master (pid {pid}) answers on {self.control_path}")
            remaining = deadline - loop.time()
            if remaining <= 0:
                return FAILURE_TIMEOUT, failure_detail(FAILURE_TIMEOUT, bytes(stderr).decode(
                    "utf-8", "replace"))
            await asyncio.wait({exited}, timeout=min(0.05, remaining))
        return None, ""

    async def _watch(self, proc: asyncio.subprocess.Process, exited: "asyncio.Task[int]",
                     drain: "asyncio.Task[None]", stderr: bytearray) -> Tuple[Optional[str], str]:
        while self._wanted:
            await asyncio.wait({exited}, timeout=self._check_interval)
            if exited.done():
                return await self._exit_failure(proc, drain, stderr)
            if self._wanted and await self._check_pid() != proc.pid:
                return FAILURE_MASTER_EXITED, (
                    f"the master is running but no longer answers on {self.control_path}")
        return None, ""

    async def _exit_failure(self, proc: asyncio.subprocess.Process, drain: "asyncio.Task[None]",
                            stderr: bytearray) -> Tuple[Optional[str], str]:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(drain), timeout=2)
        text = bytes(stderr).decode("utf-8", "replace")
        failure = ssh_exec.classify_ssh_failure(text)
        if "already exists, disabling multiplexing" in text:
            failure = FAILURE_CONTROL_PATH_BUSY
        elif failure == FAILURE_SSH:
            failure = FAILURE_MASTER_EXITED
            said = ssh_exec.first_line(text)
            return failure, f"the ssh master exited with status {proc.returncode}" + (
                f" ({said})" if said else "")
        return failure, failure_detail(failure, text)

    @staticmethod
    async def _drain(proc: asyncio.subprocess.Process, sink: bytearray) -> None:
        if proc.stderr is None:
            return
        while chunk := await proc.stderr.read(4096):
            sink += chunk
            if len(sink) > 16384:
                del sink[:-16384]

    async def _check_pid(self) -> Optional[int]:
        result = await ssh_exec.run_process(
            control_argv(self.dest, self.control_path, "check", ssh_binary=self._ssh_binary),
            timeout=5.0, verb="check", host=self.host_key)
        match = _CHECK_PID_RE.search(result.stderr_text) if result.returncode == 0 else None
        return int(match.group(1)) if match else None

    async def _clear_control_path(self) -> None:
        if not os.path.lexists(self.control_path):
            return
        orphan = await self._check_pid()
        if orphan is not None:
            logger.warning("ssh_master_orphan_exited", host=self.host_key, slot=self.slot, pid=orphan)
            await ssh_exec.run_process(
                control_argv(self.dest, self.control_path, "exit", ssh_binary=self._ssh_binary),
                timeout=5.0, verb="exit", host=self.host_key)
            for _ in range(40):
                if not os.path.lexists(self.control_path):
                    return
                await asyncio.sleep(0.05)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.control_path)

    async def _stop_process(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except TimeoutError:
            signal_group(proc, signal.SIGKILL)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=3)
        if os.path.lexists(self.control_path) and await self._check_pid() is None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.control_path)
