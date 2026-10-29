"""The tmux config file a COLD socket's server reads before it makes a pane.

WHAT PROBLEM THIS SOLVES, AND WHY NOTHING ELSE CAN. A tmux pane's
scrollback depth is fixed into its grid by ``window_pane_create`` and no
later ``set-option`` moves it. Measured three ways on tmux 3.6a, a pane
born under the stock 2000 still reports ``#{history_limit} 2000`` after a
global set, after a session-scoped set, and after ``respawn-pane -k``. So
the option has to be on the server BEFORE ``new-session`` creates the
pane, and on a cold socket it cannot be: ``set-option`` does not start a
tmux server, it exits 1 with "error connecting".

``tmux -f <file>`` is read when the SERVER STARTS, which on a cold socket
happens inside the ``new-session`` invocation itself and strictly before
the session is created. That is the only window there is, and it costs
ZERO extra processes - ``-f`` is two more argv elements on a call that
was already being made. See ``TmuxBackend.start``, which is the only
caller.

**IT IS RE-DERIVED ON EVERY LAUNCH, WHICH IS WHAT MAKES A STALE FILE
IMPOSSIBLE.** The body is rendered from the same argv fragments the
post-spawn batch sends, so there is one source of truth for what these
options are and the file cannot drift from the code that ships. Nothing
has to migrate it on upgrade and nothing has to clean it up: the next
launch overwrites it with what the running build believes.

**EVERY FAILURE HERE DEGRADES TO THE PRE-FIX LAUNCH, AND THAT DIRECTION
IS NOT NEGOTIABLE.** A user who loses scrollback depth has lost a
setting; a user who cannot start a session has lost the product. So
:func:`write_server_config` returns ``None`` rather than raising, the
caller simply omits ``-f``, and the launch is byte-identical to what it
was before this module existed.

**tmux ITSELF IS ALSO FAIL-SAFE HERE, MEASURED RATHER THAN ASSUMED**, on
tmux 3.6a, each against a real cold throwaway socket:

- a MISSING ``-f`` file: ``rc=0``, session created, options not applied;
- an UNREADABLE one (mode 000): ``rc=0``, session created;
- a MALFORMED one: ``rc=0``, session created, and THE WHOLE CONFIG IS
  DISCARDED - a valid line placed BEFORE the bad one does not apply
  either, and tmux prints nothing at all;
- on a WARM socket ``-f`` is ignored outright, because the server is
  already up.

That last-but-one point is why :func:`render_config_line` REFUSES a token
it cannot express instead of quoting it hopefully. A file we got subtly
wrong does not fail loudly, it silently costs the session every option in
it, and the only way to notice is to measure the pane afterwards - which
is exactly what ``tests/test_cold_socket_born_at_depth_real_tmux.py``
does.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

import structlog

from src.core.tmux_command_batch import TmuxCommand

logger = structlog.get_logger()

# state directory
SERVER_CONFIG_FILENAME: str = "cloude-tmux.conf"

_UNSAFE_IN_LINE: str = " \t\n\r\"'\\#;$"


def render_config_line(command: TmuxCommand) -> Optional[str]:
    """Render one tmux command as a config-file line.

    A tmux config line is the command exactly as it would be typed after
    ``tmux``, so this is a space join - but only for tokens that survive
    the join unchanged.

    Args:
        command: the argv fragment, with no ``tmux -L`` prefix, for
            example ``("set-option", "-g", "history-limit", "50000")``.

    Returns:
        str: the line, without a trailing newline. ``None`` when the
        command is empty or any token carries a character tmux's config
        lexer would read as structure, because the whole file is then
        unsafe to write.
    """
    tokens = [str(token) for token in command]
    if not tokens:
        return None
    for token in tokens:
        if not token or any(char in token for char in _UNSAFE_IN_LINE):
            return None
    return " ".join(tokens)


def render_config(commands: Sequence[TmuxCommand]) -> Optional[str]:
    if not commands:
        return None
    lines: List[str] = []
    for command in commands:
        line = render_config_line(command)
        if line is None:
            logger.warning(
                "tmux_server_config_refused",
                reason="a token cannot be expressed as a config line",
                command=" ".join(str(token) for token in command),
            )
            return None
        lines.append(line)
    return "".join(f"{line}\n" for line in lines)


def write_server_config(
    directory: Path, commands: Sequence[TmuxCommand]
) -> Optional[Path]:
    """Write the config atomically and hand back its path.

    The write is the pattern from ``Settings.update_settings_config()``:
    a temp file in the SAME directory, flush, fsync, ``os.replace``. A
    half-written config is worse than a missing one, because tmux reads a
    truncated file as a malformed one and silently discards every option
    in it.

    NEVER RAISES. Every reason this can fail - a read-only directory, a
    full disk, permissions, a command that could not be rendered - is a
    reason to launch the session WITHOUT ``-f``, exactly as the app did
    before this existed. Losing scrollback depth is survivable; refusing
    to open a session is not.

    Args:
        directory: where the file lives, normally the app's state
            directory. Created if absent.
        commands: the commands the server should run at startup.

    Returns:
        Path: the file written, to be passed to tmux as ``-f``. ``None``
        when it could not be written, meaning "launch without it".

    Example:
        >>> write_server_config(state_dir, [backend._history_limit_command()])
        PosixPath('.../cloude-tmux.conf')
    """
    body = render_config(commands)
    if body is None:
        return None

    target = directory / SERVER_CONFIG_FILENAME
    tmp_name: Optional[str] = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            prefix=f".{SERVER_CONFIG_FILENAME}.", suffix=".tmp", dir=str(directory)
        )
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, target)
        tmp_name = None
        return target
    except (OSError, ValueError) as exc:
        logger.warning(
            "tmux_server_config_write_failed",
            path=str(target),
            error=f"{type(exc).__name__}: {exc}",
        )
        return None
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
