
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import signal
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import structlog

logger = structlog.get_logger()

SSH_BINARY = "/usr/bin/ssh"


class SshArgumentError(ValueError):
    pass



_TARGET_PART = r"[A-Za-z0-9_][A-Za-z0-9._+-]*"
_TARGET_RE = re.compile(rf"(?:{_TARGET_PART}@)?{_TARGET_PART}")
TARGET_MAX = 254


def validate_ssh_target(target: object) -> str:
    if (not isinstance(target, str) or len(target) > TARGET_MAX
            or _TARGET_RE.fullmatch(target) is None):
        raise SshArgumentError(
            f"ssh target {str(target)[:64]!r} is refused: use an alias or user@host of letters, "
            "digits and ._+- only, each part starting with a letter, digit or underscore"
        )
    return target


def validate_ssh_port(port: object) -> Optional[int]:
    if port is None:
        return None
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SshArgumentError(f"ssh port {port!r} is refused: use an integer from 1 to 65535")
    return port


@dataclass(frozen=True)
class SshDestination:

    target: str
    port: Optional[int] = None

    def __post_init__(self) -> None:
        validate_ssh_target(self.target)
        validate_ssh_port(self.port)

    def port_args(self) -> List[str]:
        return [] if self.port is None else ["-p", str(self.port)]


_CONTROL_PATH_RE = re.compile(r"/[A-Za-z0-9._/+-]+")

CONTROL_PATH_MAX = 86


def validate_control_path(path: str) -> str:
    if not isinstance(path, str) or _CONTROL_PATH_RE.fullmatch(path) is None:
        raise SshArgumentError(f"control path {str(path)[:96]!r} has characters ssh would expand")
    if len(path) > CONTROL_PATH_MAX:
        raise SshArgumentError(
            f"control path {path!r} is {len(path)} bytes; a unix socket allows {CONTROL_PATH_MAX}"
        )
    return path



HARDENING_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("BatchMode", "yes"),
    ("StrictHostKeyChecking", "accept-new"),
    ("ForwardAgent", "no"),
    ("ForwardX11", "no"),
    ("ClearAllForwardings", "yes"),
    ("Tunnel", "no"),
    ("PermitLocalCommand", "no"),
    ("RemoteCommand", "none"),
    ("RequestTTY", "no"),
    ("EscapeChar", "none"),
    ("LogLevel", "ERROR"),
    ("ConnectTimeout", "15"),
    ("ServerAliveInterval", "15"),
    ("ServerAliveCountMax", "3"),
)


def _options(pairs: Iterable[Tuple[str, str]]) -> List[str]:
    words: List[str] = []
    for key, value in pairs:
        words += ["-o", f"{key}={value}"]
    return words


def _remote_command(remote_command: str) -> str:
    if not isinstance(remote_command, str) or not remote_command or "\0" in remote_command:
        raise SshArgumentError("a remote command must be a non-empty string with no NUL byte")
    return remote_command


def master_argv(dest: SshDestination, control_path: str, *, ssh_binary: str = SSH_BINARY) -> List[str]:
    control = (("ControlMaster", "yes"), ("ControlPersist", "no"),
               ("ControlPath", validate_control_path(control_path)))
    return [ssh_binary, *_options(HARDENING_OPTIONS), *_options(control),
            *dest.port_args(), "-N", "--", dest.target]


def mux_argv(dest: SshDestination, control_path: str, remote_command: str, *,
             ssh_binary: str = SSH_BINARY) -> List[str]:
    control = (("ControlMaster", "no"), ("ControlPath", validate_control_path(control_path)),
               ("ProxyCommand", "false"))
    return [ssh_binary, *_options(HARDENING_OPTIONS), *_options(control),
            *dest.port_args(), "--", dest.target, _remote_command(remote_command)]


def direct_argv(dest: SshDestination, remote_command: str, *,
                ssh_binary: str = SSH_BINARY,
                pre_options: Sequence[Tuple[str, str]] = ()) -> List[str]:
    for key, value in pre_options:
        if not key or any(ch in key + value for ch in "\n\r\0"):
            raise SshArgumentError("an ssh option may not be empty or hold a newline or NUL byte")
    control = (("ControlMaster", "no"), ("ControlPath", "none"))
    return [ssh_binary, *_options(pre_options), *_options(HARDENING_OPTIONS), *_options(control),
            *dest.port_args(), "--", dest.target, _remote_command(remote_command)]


def control_argv(dest: SshDestination, control_path: str, operation: str, *,
                 ssh_binary: str = SSH_BINARY) -> List[str]:
    if operation not in ("check", "exit"):
        raise SshArgumentError(f"ssh -O {operation!r} is not used here")
    control = (("ControlPath", validate_control_path(control_path)),)
    return [ssh_binary, *_options(HARDENING_OPTIONS), *_options(control),
            *dest.port_args(), "-O", operation, "--", dest.target]


def config_argv(dest: SshDestination, *, ssh_binary: str = SSH_BINARY) -> List[str]:
    control = (("ControlMaster", "no"), ("ControlPath", "none"))
    return [ssh_binary, "-G", *_options(HARDENING_OPTIONS), *_options(control),
            *dest.port_args(), "--", dest.target]


def parse_effective_config(text: str) -> Dict[str, str]:
    config: Dict[str, str] = {}
    for line in text.splitlines():
        key, _, value = line.strip().partition(" ")
        if key:
            config.setdefault(key.lower(), value.strip())
    return config



POSIX_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ksh93", "mksh", "ash"})

SH_STDIN_COMMAND = "exec /bin/sh -s"


def is_posix_shell(shell_path: Optional[str]) -> bool:
    if not shell_path:
        return False
    return shell_path.rsplit("/", 1)[-1] in POSIX_SHELLS


def posix_quote(word: str) -> str:
    if not isinstance(word, str) or "\0" in word:
        raise SshArgumentError("a remote argument must be a str with no NUL byte")
    return "'" + word.replace("'", "'\"'\"'") + "'"


def posix_join(argv: Sequence[str]) -> str:
    if isinstance(argv, str) or not argv:
        raise SshArgumentError("an argv list with at least one word is required")
    return " ".join(posix_quote(word) for word in argv)


def sh_c(script: str) -> str:
    if not isinstance(script, str) or not script.strip():
        raise SshArgumentError("a remote script may not be empty")
    return "exec /bin/sh -c " + posix_quote(script)


def argv_command(argv: Sequence[str]) -> str:
    return sh_c("exec " + posix_join(argv))



FAILURE_UNREACHABLE = "unreachable"
FAILURE_TIMEOUT = "timeout"
FAILURE_AUTH = "auth_failed"
FAILURE_HOST_KEY_CHANGED = "host_key_changed"
FAILURE_HOST_KEY_UNVERIFIED = "host_key_unverified"
FAILURE_CHANNEL_REFUSED = "channel_refused"
FAILURE_SSH = "ssh_failed"
FAILURE_SSH_UNAVAILABLE = "ssh_unavailable"
FAILURE_OVERFLOW = "output_overflow"

_FAILURE_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    (FAILURE_HOST_KEY_CHANGED, re.compile(
        r"remote host identification has changed|host key for \S+ has changed", re.I)),
    (FAILURE_HOST_KEY_UNVERIFIED, re.compile(
        r"host key verification failed|no \S+ host key is known|revoked host key", re.I)),
    (FAILURE_AUTH, re.compile(
        r"permission denied|too many authentication failures|no more authentication methods", re.I)),
    (FAILURE_CHANNEL_REFUSED, re.compile(r"administratively prohibited", re.I)),
    (FAILURE_UNREACHABLE, re.compile(
        r"could not resolve hostname|connection refused|timed out|no route to host"
        r"|network is unreachable|host is down|connection closed by|connection reset"
        r"|kex_exchange_identification|not responding|closed by remote host|broken pipe", re.I)),
)

FAILURE_MEANING: Dict[str, str] = {
    FAILURE_UNREACHABLE: "the host could not be reached",
    FAILURE_TIMEOUT: "ssh did not finish in time (the network is slow, or an agent is waiting for approval)",
    FAILURE_AUTH: "the login was refused: add the key to your ssh agent (batch mode never prompts)",
    FAILURE_HOST_KEY_CHANGED: "the host key changed since it was first trusted, so the connection was refused; "
                              "verify the new key in a terminal before trusting it",
    FAILURE_HOST_KEY_UNVERIFIED: "ssh could not verify the host key",
    FAILURE_CHANNEL_REFUSED: "the host refused another ssh channel (its MaxSessions limit)",
    FAILURE_SSH: "ssh failed",
    FAILURE_SSH_UNAVAILABLE: "the ssh program could not be started",
    FAILURE_OVERFLOW: "the host sent more output than the cap allows",
}


def classify_ssh_failure(stderr_text: str) -> str:
    for name, pattern in _FAILURE_PATTERNS:
        if pattern.search(stderr_text or ""):
            return name
    return FAILURE_SSH


def first_line(text: str, limit: int = 300) -> str:
    for line in (text or "").splitlines():
        line = line.strip().strip("@").strip()
        if line:
            return line[:limit]
    return ""


def failure_detail(failure: str, stderr_text: str) -> str:
    meaning = FAILURE_MEANING.get(failure, failure.replace("_", " "))
    said = first_line(stderr_text)
    return f"{meaning} ({said})" if said else meaning



@dataclass(frozen=True)
class ExecResult:

    returncode: Optional[int]
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    overflowed: bool = False
    spawn_error: Optional[str] = None
    elapsed_ms: int = 0

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", "replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", "replace")

    @property
    def failure(self) -> Optional[str]:
        if self.spawn_error is not None:
            return FAILURE_SSH_UNAVAILABLE
        if self.timed_out:
            return FAILURE_TIMEOUT
        if self.overflowed:
            return FAILURE_OVERFLOW
        if self.returncode == 255:
            return classify_ssh_failure(self.stderr_text)
        return None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.failure is None


def signal_group(proc: asyncio.subprocess.Process, sig: int = signal.SIGKILL) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(sig)


async def collect_process(proc: asyncio.subprocess.Process, *, stdin_data: Optional[bytes],
                          timeout: float, max_output: int, max_stderr: int,
                          started: float) -> ExecResult:
    out, err = bytearray(), bytearray()
    overflowed = timed_out = False

    async def pump(stream: Optional[asyncio.StreamReader], sink: bytearray, cap: int) -> None:
        nonlocal overflowed
        if stream is None:
            return
        while chunk := await stream.read(65536):
            room = cap - len(sink)
            if len(chunk) > room:
                sink += chunk[:max(room, 0)]
                overflowed = True
                signal_group(proc)
                return
            sink += chunk

    async def feed() -> None:
        if proc.stdin is None:
            return
        try:
            if stdin_data:
                proc.stdin.write(stdin_data)
                await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                proc.stdin.close()

    try:
        async with asyncio.timeout(timeout):
            await asyncio.gather(pump(proc.stdout, out, max_output),
                                 pump(proc.stderr, err, max_stderr), feed())
            await proc.wait()
    except TimeoutError:
        timed_out = True
    finally:
        signal_group(proc)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5)
    return ExecResult(
        returncode=None if (timed_out or overflowed) else proc.returncode,
        stdout=bytes(out), stderr=bytes(err), timed_out=timed_out, overflowed=overflowed,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


async def run_process(argv: Sequence[str], *, stdin_data: Optional[bytes] = None,
                      timeout: float = 30.0, max_output: int = 1 << 20,
                      max_stderr: int = 64 << 10, verb: str = "exec",
                      host: str = "") -> ExecResult:
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        logger.warning("ssh_exec_spawn_failed", host=host, verb=verb, error=type(exc).__name__)
        return ExecResult(None, b"", b"", spawn_error=f"{type(exc).__name__}: {exc}",
                          elapsed_ms=int((time.monotonic() - started) * 1000))
    result = await collect_process(proc, stdin_data=stdin_data, timeout=timeout,
                                   max_output=max_output, max_stderr=max_stderr, started=started)
    log = logger.debug if result.ok else logger.info
    log("ssh_exec", host=host, verb=verb, rc=result.returncode, failure=result.failure,
        stdin_bytes=len(stdin_data or b""), stdout_bytes=len(result.stdout),
        stderr_bytes=len(result.stderr), elapsed_ms=result.elapsed_ms)
    return result
