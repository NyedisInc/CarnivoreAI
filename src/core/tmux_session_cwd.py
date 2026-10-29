
from __future__ import annotations

import shutil
import subprocess
from typing import Callable, Optional

import structlog

from src.core.tmux_discovery import TmuxVersionSkewError, tmux_argv_prefix

logger = structlog.get_logger()

CWD_PROBE_TIMEOUT_SECONDS: float = 5.0

SESSION_PATH_FORMAT = "#{session_path}"

PANE_PATH_FORMAT = "#{pane_current_path}"

_TARGET_SEPARATORS = (":", ".")


def probe_session_working_dir(
    name: str,
    *,
    socket: str,
    timeout: float = CWD_PROBE_TIMEOUT_SECONDS,
    fmt: str = SESSION_PATH_FORMAT,
) -> Optional[str]:
    """Read one tmux session's working directory, or answer that we cannot.

    Description: runs ``tmux -L <socket> display-message -p -t '=<name>'
      '#{session_path}'``. The ``=`` prefix is tmux's EXACT-MATCH target
      operator: without it tmux treats the target as a pattern, so a
      session named ``fs`` would match ``fs2`` and this function would
      confidently return a different session's directory. That is an
      identity error, and it is silent, so it is worth the two
      characters.

      NEVER RAISES and NEVER GUESSES. Every failure - tmux absent, a
      timeout, a non-zero exit, an empty answer, an undecodable byte
      string - returns None, which means CANNOT DETERMINE and must not
      be read as "no working directory".
    Inputs: name (str) - the tmux session name. socket (str) - the tmux
      socket the session lives on. timeout (float) - seconds. fmt (str) -
      :data:`SESSION_PATH_FORMAT` (default) or :data:`PANE_PATH_FORMAT`.
    Output: str | None - the session's working directory, or None when
      it could not be determined.
    Example: probe_session_working_dir('cloude_a', socket='cloude')
    """
    if not name:
        return None
    if any(sep in name for sep in _TARGET_SEPARATORS):
        logger.warning(
            "session_cwd_probe_unsafe_name",
            tmux_name=name,
            note="name contains a tmux target separator; cannot be probed",
        )
        return None
    try:
        base = tmux_argv_prefix(socket)
    except TmuxVersionSkewError as exc:
        logger.warning("session_cwd_probe_skew", tmux_name=name, tmux_socket=socket, error=str(exc),
                       note="working directory CANNOT BE DETERMINED; attribution unknown")
        return None
    if not shutil.which(base[0]):
        return None
    try:
        completed = subprocess.run(
            [
                *base,
                "display-message",
                "-p",
                "-t",
                f"={name}:",
                fmt,
            ],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning(
            "session_cwd_probe_failed",
            tmux_name=name,
            tmux_socket=socket,
            error=str(exc),
            note="working directory CANNOT BE DETERMINED; attribution unknown",
        )
        return None
    if completed.returncode != 0:
        logger.info(
            "session_cwd_probe_nonzero",
            tmux_name=name,
            tmux_socket=socket,
            returncode=completed.returncode,
            stderr=completed.stderr.decode("utf-8", errors="replace")[:200],
        )
        return None
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    return text or None


def make_working_dir_probe(
    socket: str, *, timeout: float = CWD_PROBE_TIMEOUT_SECONDS
) -> Callable[[str], Optional[str]]:

    def _probe(name: str) -> Optional[str]:
        return probe_session_working_dir(name, socket=socket, timeout=timeout)

    return _probe
