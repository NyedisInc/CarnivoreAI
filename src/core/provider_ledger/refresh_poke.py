"""Making Claude Code refresh its own token, without ever holding one.

**THE EXIT CODE PROVES NOTHING AND IS NEVER THE SUCCESS TEST.** Success
is ``expiresAt`` MOVING FORWARD, measured by re-reading the credential,
and that judgement lives in
:mod:`src.core.provider_ledger.poller_poke`. Reading exit 0 as success
here would be gotcha 11 exactly: a check that passes because it looked at
nothing.

**THE CHILD ENVIRONMENT IS BUILT, NEVER COPIED** (``ENV_ALLOW_LIST``): a
few basics plus the profile's ``CLAUDE_CONFIG_DIR``. A server started from
an agent pane inherits that pane's Claude session variables
(``CLAUDECODE``, ``CLAUDE_CODE_SESSION_ID``, the messaging socket and so
on), and a copy-and-strip list can never name them all. The single use
``CLAUDE_CODE_OAUTH_REFRESH_TOKEN`` is the worst of the credential names,
since an inherited one is SPENT rather than merely honoured;
``SUPPRESSING_ENV_VARS`` stays as the independent statement of what must
never reach a child, and the logout path for ``codex`` still strips by it.

**THE CHILD IS A PROCESS TREE AND THE STOP HAS TO REACH ALL OF IT.**
``claude`` shells out to ``security``, so the spawn takes a session of
its own and both the timeout and a cancellation signal the process
GROUP; signalling the direct child alone leaves the grandchild running.
The timeout asks first (SIGTERM) and forces only after a grace period.

**STDOUT AND STDERR ARE CAPTURED AND NEVER LOGGED BEYOND THEIR BYTE
LENGTHS AND A SET OF FIXED LABELS** (:func:`classify_output`). A failing
``claude`` prints authentication error strings, and there is no
redaction processor in this codebase: not passing the value IS the
mechanism, the same rule :mod:`keychain` states. A label is a constant
this module chose, so it can say "the output mentioned invalid_grant"
without a byte of the output leaving the process.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.provider_ledger.credentials import is_default_claude_dir
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS
from src.core.sessions.agent_update import CLAUDE_INSTALL_CANDIDATES

logger = structlog.get_logger()

__all__ = [
    "LOGIN_EXPIRED",
    "OUTPUT_SIGNALS",
    "classify_output",
    "ENV_ALLOW_LIST",
    "KEEPALIVE_ARGS",
    "NEEDS_LOGIN",
    "POKE_BINARY_MISSING",
    "POKE_ERRORED",
    "POKE_EXIT_NONZERO",
    "POKE_NO_REFRESH",
    "POKE_SPAWN_FAILED",
    "POKE_TIMED_OUT",
    "POKE_TIMEOUT_SECONDS",
    "COMMAND_TIMEOUT_SECONDS",
    "PokeOutcome",
    "TEST_MODE_ENV",
    "build_claude_command",
    "build_poke",
    "ChildResult",
    "failure_reason",
    "resolve_binary",
    "resolve_claude_binary",
    "run_child",
    "run_poke",
]

KEEPALIVE_ARGS: Tuple[str, ...] = (
    "-p",
    "ok",
    "--model",
    "haiku",
    "--no-session-persistence",
    "--settings",
    '{"disableAllHooks":true}',
    "--strict-mcp-config",
    "--tools",
    "",
)

ENV_ALLOW_LIST: Tuple[str, ...] = (
    "HOME",
    "PATH",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
)

PROFILE_ENV_VAR = PROFILE_ENV_VARS["claude"]

SUPPRESSING_ENV_VARS: Tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_API_KEY",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
    "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
    "CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR",
    "CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR",
    "CLAUDE_CODE_HOST_CREDS_FILE",
    "CLAUDE_CODE_HOST_AUTH_ENV_VAR",
    "CLAUDE_SESSION_INGRESS_TOKEN_FILE",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "CLAUDE_CODE_SESSION_ACCESS_TOKEN",
    "CLAUDE_TRUSTED_DEVICE_TOKEN",
    "CLAUDE_BRIDGE_OAUTH_TOKEN",
    "CLAUDE_CODE_HFI_BEARER_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_GATEWAY",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS",
    "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
    "AWS_BEARER_TOKEN_BEDROCK",
    "ANTHROPIC_AWS_API_KEY",
    "ANTHROPIC_FOUNDRY_API_KEY",
    "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_HOST",
    "ANTHROPIC_BEDROCK_BASE_URL",
    "ANTHROPIC_BEDROCK_MANTLE_BASE_URL",
    "ANTHROPIC_VERTEX_BASE_URL",
    "ANTHROPIC_FOUNDRY_BASE_URL",
    "ANTHROPIC_AWS_BASE_URL",
    "ANTHROPIC_GOOGLE_CLOUD_BASE_URL",
    "ANTHROPIC_UNIX_SOCKET",
    "CLAUDE_CODE_API_BASE_URL",
    "CLAUDE_CODE_CUSTOM_OAUTH_URL",
    "CLAUDE_AI_HOST",
    "CLAUDE_AI_ORIGIN",
    "CLAUDE_AI_AUTHORIZE_URL",
    "CLAUDE_HOST",
    "CLAUDE_LOCAL_OAUTH_API_BASE",
    "CLAUDE_LOCAL_OAUTH_APPS_BASE",
    "CLAUDE_LOCAL_OAUTH_CONSOLE_BASE",
    "CLAUDE_CODE_PROXY_URL",
    "CLAUDE_CODE_PROXY_HOST",
    "CLAUDE_CODE_HTTP_PROXY",
    "CLAUDE_CODE_HTTPS_PROXY",
    "CLAUDE_CODE_PROXY_AUTHENTICATE",
    "CLAUDE_CODE_CLIENT_CERT",
    "CLAUDE_CODE_CLIENT_KEY",
    "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_CONFIG_DIR",
    "CLAUDE_SECURESTORAGE_CONFIG_DIR",
    "CLAUDE_ENV_FILE",
    "ANTHROPIC_CUSTOM_HEADERS",
)

POKE_TIMEOUT_SECONDS = 120.0

COMMAND_TIMEOUT_SECONDS = 30.0

STOP_GRACE_SECONDS = 5.0

TEST_MODE_ENV = "CLOUDE_TEST_MODE"

POKE_BINARY_MISSING = "poke_binary_missing"
POKE_SPAWN_FAILED = "poke_spawn_failed"
POKE_TIMED_OUT = "poke_timed_out"
POKE_EXIT_NONZERO = "poke_exit_nonzero"
POKE_NO_REFRESH = "poke_no_refresh"

NEEDS_LOGIN = "needs_login"

# could not
POKE_ERRORED = "poke_errored"

LOGIN_EXPIRED = "login_expired"


@dataclass(frozen=True)
class PokeOutcome:
    """What one attempt to run the poke did. NEVER whether it worked.

    Description: this reports the PROCESS, not the refresh. Whether the
      credential actually moved is decided by re-reading it, in
      :mod:`poller_poke`, because a keepalive exits 0 either way.

    Attributes:
        ran: whether a child process was started at all. ``False`` means
            the binary was not there or could not be executed.
        exit_code: the child's status, or ``None`` when it never
            finished (killed on timeout) or never started.
        timed_out: whether the bound elapsed and the child was stopped.
        duration_seconds: wall time for the whole attempt.
        stdout_bytes / stderr_bytes: how much each stream carried.
        output_signals: which of :data:`OUTPUT_SIGNALS` appeared in
            either stream, as their fixed labels. NEVER the text.
    """

    ran: bool
    exit_code: Optional[int]
    timed_out: bool
    duration_seconds: float
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    output_signals: Tuple[str, ...] = ()


OUTPUT_SIGNALS: Tuple[Tuple[str, str], ...] = (
    ("invalid_grant", "invalid_grant"),
    ("refresh_token", "refresh token"),
    ("unauthorized", "unauthorized"),
    ("forbidden", "forbidden"),
    ("expired", "expired"),
    ("not_logged_in", "not logged in"),
    ("logged_out", "logged out"),
    ("login", "login"),
    ("oauth", "oauth"),
    ("keychain", "keychain"),
    ("rate_limit", "rate limit"),
    ("network", "network"),
    ("timeout", "timed out"),
    ("error", "error"),
    ("failed", "failed"),
)


def classify_output(*streams: Optional[bytes]) -> Tuple[str, ...]:
    text = " ".join((s or b"").decode("utf-8", "replace").lower() for s in streams)
    return tuple(label for label, phrase in OUTPUT_SIGNALS if phrase in text)


def resolve_binary(name: str, fallbacks: Sequence[str] = ()) -> Optional[str]:
    if os.environ.get(TEST_MODE_ENV):
        return None
    found = shutil.which(name)
    if found is None:
        found = _first_installed(fallbacks)
    if found is None:
        return None
    if not os.path.isabs(found) or not os.access(found, os.X_OK):
        logger.warning("provider_ledger_poke_binary_not_absolute", binary=name)
        return None
    return found


def _first_installed(candidates: Sequence[str]) -> Optional[str]:
    for candidate in candidates:
        path = os.path.expanduser(candidate)
        if os.path.isabs(path) and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def resolve_claude_binary() -> Optional[str]:
    return resolve_binary("claude", CLAUDE_INSTALL_CANDIDATES)


def build_claude_command(
    profile_dir: Optional[str], claude_binary: str, *args: str
) -> Tuple[List[str], Dict[str, str]]:
    argv = [claude_binary, *args]
    env = {k: os.environ[k] for k in ENV_ALLOW_LIST if k in os.environ}
    if profile_dir is not None and not is_default_claude_dir(profile_dir):
        env[PROFILE_ENV_VAR] = profile_dir
    return argv, env


def build_poke(
    profile_dir: Optional[str], claude_binary: str
) -> Tuple[List[str], Dict[str, str]]:
    return build_claude_command(profile_dir, claude_binary, *KEEPALIVE_ARGS)


def failure_reason(outcome: PokeOutcome) -> str:
    if outcome.timed_out:
        return POKE_TIMED_OUT
    if not outcome.ran:
        return POKE_SPAWN_FAILED
    if outcome.exit_code != 0:
        return POKE_EXIT_NONZERO
    return POKE_NO_REFRESH


def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    _signal_process_group(process, signal.SIGKILL)


def _signal_process_group(process: asyncio.subprocess.Process, signum: int) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signum)


async def _stop_process_group(process: asyncio.subprocess.Process) -> None:
    _signal_process_group(process, signal.SIGTERM)
    with suppress(asyncio.TimeoutError, ProcessLookupError):
        await asyncio.wait_for(process.wait(), timeout=STOP_GRACE_SECONDS)
        return
    _kill_process_group(process)
    with suppress(asyncio.TimeoutError, ProcessLookupError):
        await asyncio.wait_for(process.wait(), timeout=5.0)


@dataclass(frozen=True)
class ChildResult:

    ran: bool
    exit_code: Optional[int]
    timed_out: bool
    duration_seconds: float
    stdout: bytes = b""
    stderr: bytes = b""
    spawn_error: Optional[str] = None


async def run_child(
    argv: List[str],
    env: Dict[str, str],
    *,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
    stdin: Optional[bytes] = None,
    cwd: Optional[str] = None,
) -> ChildResult:
    started = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            env=env,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL if stdin is None else asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        return ChildResult(
            ran=False,
            exit_code=None,
            timed_out=False,
            duration_seconds=time.monotonic() - started,
            spawn_error=type(exc).__name__,
        )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(input=stdin), timeout=timeout)
    except asyncio.TimeoutError:
        await _stop_process_group(process)
        return ChildResult(
            ran=True,
            exit_code=None,
            timed_out=True,
            duration_seconds=time.monotonic() - started,
        )
    except asyncio.CancelledError:
        # server stopped
        try:
            await _stop_process_group(process)
        except asyncio.CancelledError:
            _kill_process_group(process)
        raise
    return ChildResult(
        ran=True,
        exit_code=process.returncode,
        timed_out=False,
        duration_seconds=time.monotonic() - started,
        stdout=stdout or b"",
        stderr=stderr or b"",
    )


@dataclass(frozen=True)
class StreamResult:

    ran: bool
    exit_code: Optional[int]
    timed_out: bool
    stopped: bool
    duration_seconds: float
    stderr_tail: bytes = b""
    spawn_error: Optional[str] = None


STREAM_LINE_LIMIT = 8 << 20
STREAM_STDERR_KEEP = 16 << 10


async def _drain_stderr(stream: asyncio.StreamReader, keep: List[bytes]) -> None:
    tail = b""
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        tail = (tail + chunk)[-STREAM_STDERR_KEEP:]
    keep.append(tail)


async def run_child_streaming(
    argv: List[str],
    env: Dict[str, str],
    *,
    on_line: Callable[[bytes], bool],
    timeout: float,
    stdin: Optional[bytes] = None,
    cwd: Optional[str] = None,
    on_started: Optional[Callable[[int], Awaitable[None]]] = None,
) -> StreamResult:
    started = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, env=env, cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL if stdin is None else asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True, limit=STREAM_LINE_LIMIT)
    except (OSError, ValueError) as exc:
        return StreamResult(False, None, False, False, time.monotonic() - started, spawn_error=type(exc).__name__)
    stopped, tail = False, []
    stderr_task = asyncio.ensure_future(_drain_stderr(process.stderr, tail))

    async def pump() -> None:
        nonlocal stopped
        if on_started is not None:
            await on_started(process.pid)
        if stdin is not None:
            try:
                process.stdin.write(stdin)
                await process.stdin.drain()
                process.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass
        while True:
            try:
                line = await process.stdout.readline()
            except ValueError:
                continue
            if not line:
                return
            if on_line(line):
                stopped = True
                return

    timed_out = False
    try:
        try:
            await asyncio.wait_for(pump(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
        if timed_out or stopped:
            await _stop_process_group(process)
        else:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=STOP_GRACE_SECONDS)
            if process.returncode is None:
                await _stop_process_group(process)
    except BaseException:
        try:
            await _stop_process_group(process)
        except asyncio.CancelledError:
            _kill_process_group(process)
        raise
    finally:
        with suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(stderr_task, timeout=2.0)
        stderr_task.cancel()
    return StreamResult(True, None if (timed_out or stopped) else process.returncode, timed_out, stopped,
                        time.monotonic() - started, tail[0] if tail else b"")


async def run_poke(
    argv: List[str],
    env: Dict[str, str],
    *,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
) -> PokeOutcome:
    result = await run_child(argv, env, timeout=timeout)
    if not result.ran:
        logger.warning("provider_ledger_poke_unavailable", error=result.spawn_error)
        return PokeOutcome(
            ran=False,
            exit_code=None,
            timed_out=False,
            duration_seconds=result.duration_seconds,
        )
    if result.timed_out:
        logger.warning("provider_ledger_poke_timed_out", timeout=timeout)
        return PokeOutcome(
            ran=True,
            exit_code=None,
            timed_out=True,
            duration_seconds=result.duration_seconds,
        )
    signals = classify_output(result.stdout, result.stderr)
    logger.info(
        "provider_ledger_poke_ran",
        exit_code=result.exit_code,
        stdout_bytes=len(result.stdout),
        stderr_bytes=len(result.stderr),
        output_signals=list(signals),
    )
    return PokeOutcome(
        ran=True,
        exit_code=result.exit_code,
        timed_out=False,
        duration_seconds=result.duration_seconds,
        stdout_bytes=len(result.stdout),
        stderr_bytes=len(result.stderr),
        output_signals=signals,
    )


_credential_listeners: List[Callable[[object, object], None]] = []


def add_credential_listener(listener: Callable[[object, object], None]) -> None:
    _credential_listeners.append(listener)


def notify_credential(account: object, credential: object) -> None:
    for listener in list(_credential_listeners):
        try:
            listener(account, credential)
        except Exception as exc:  # noqa: BLE001
            logger.warning("provider_ledger_credential_listener_failed", error=type(exc).__name__)
