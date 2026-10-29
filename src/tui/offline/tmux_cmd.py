
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

import structlog

logger = structlog.get_logger(__name__)

ALLOWED_COMMANDS = frozenset(
    {"list-sessions", "list-panes", "display-message", "has-session", "attach-session", "resize-window", "capture-pane"}
)

NO_CONFIG = ("-f", "/dev/null")

_VALUE_OPTIONS = frozenset({"-S", "-L", "-f"})

SEP = "\x1f"

NOT_RUNNING_MARKERS = ("no server running", "error connecting to", "connection refused")

QUERY_TIMEOUT_SECONDS = 5.0


class OfflineTmuxError(Exception):
    pass


class TmuxNotRunning(OfflineTmuxError):
    """No tmux server answers on the socket: the sessions are gone."""


class TmuxCommandFailed(OfflineTmuxError):
    """tmux ran but refused, timed out, or could not be executed; ``detail`` is its first stderr line."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class TmuxTarget:

    binary: str
    socket_path: str

    @property
    def socket_name(self) -> str:
        return os.path.basename(self.socket_path)

    def prefix(self) -> tuple[str, ...]:
        return (self.binary, "-S", self.socket_path, *NO_CONFIG)


def session_target(name: str) -> str:
    return f"={name}"


def window_target(name: str) -> str:
    return f"={name}:"


def prefixed_argv(prefix: Sequence[str], command: str, *args: str) -> tuple[str, ...]:
    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"tmux command not allowed offline: {command}")
    if len(prefix) not in (3, 5) or prefix[1] not in ("-S", "-L") or (len(prefix) == 5 and prefix[3] != "-f"):
        raise ValueError("a tmux prefix is (binary, -S or -L, socket[, -f, file])")
    return tuple(prefix) + (command,) + tuple(args)


def command_argv(target: TmuxTarget, command: str, *args: str) -> tuple[str, ...]:
    return prefixed_argv(target.prefix(), command, *args)


def list_sessions_argv(target: TmuxTarget) -> tuple[str, ...]:
    fmt = SEP.join(("#{session_id}", "#{session_created}", "#{session_attached}", "#{session_name}"))
    return command_argv(target, "list-sessions", "-F", fmt)


def list_panes_argv(target: TmuxTarget) -> tuple[str, ...]:
    return command_argv(target, "list-panes", "-a", "-F", SEP.join(("#{session_id}", "#{pane_dead}", "#{pane_dead_status}")))


def server_info_argv(target: TmuxTarget) -> tuple[str, ...]:
    return command_argv(target, "display-message", "-p", SEP.join(("#{pid}", "#{socket_path}")))


def has_session_argv(prefix: Sequence[str], name: str) -> tuple[str, ...]:
    return prefixed_argv(prefix, "has-session", "-t", session_target(name))


def command_word(argv: Sequence[str]) -> str:
    i = 1
    while i < len(argv) and argv[i] in _VALUE_OPTIONS:
        i += 2
    return argv[i] if i < len(argv) else ""


def pane_size_argv(prefix: Sequence[str], name: str) -> tuple[str, ...]:
    fmt = SEP.join(("#{window_width}", "#{window_height}", "#{status}", "#{prefix}"))
    return prefixed_argv(prefix, "display-message", "-p", "-t", window_target(name), fmt)


def clean_env(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k != "TMUX"}


def run_query(argv: tuple[str, ...], env: Optional[Mapping[str, str]] = None) -> str:
    word = command_word(argv)
    if word not in ALLOWED_COMMANDS:
        raise ValueError(f"tmux command not allowed offline: {word}")
    try:
        done = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=QUERY_TIMEOUT_SECONDS, check=False,
            env=clean_env(os.environ if env is None else env),
        )
    except subprocess.TimeoutExpired as err:
        logger.warning("tui_offline_tmux_timeout", command=word)
        raise TmuxCommandFailed("tmux did not answer in time") from err
    except OSError as err:
        logger.warning("tui_offline_tmux_exec_failed", command=word, error=err.strerror)
        raise TmuxCommandFailed(f"could not run {argv[0]}: {err.strerror}") from err
    if done.returncode == 0:
        return done.stdout
    first = (done.stderr.strip().splitlines() or [f"exit status {done.returncode}"])[0]
    if any(marker in first.lower() for marker in NOT_RUNNING_MARKERS):
        raise TmuxNotRunning(first)
    raise TmuxCommandFailed(first)


def probe_session(prefix: Sequence[str], name: str, env: Optional[Mapping[str, str]] = None) -> None:
    run_query(has_session_argv(prefix, name), env)
