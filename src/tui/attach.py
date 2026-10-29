"""Attach the terminal to a session's tmux pane: the argv, the plan and the one blocking run.

The TUI is a plain terminal program, not a tmux window. Enter on a row suspends it and runs
``tmux -L <socket> attach-session -t =<stored tmux name>``; detaching returns to the TUI. The name is the
STORED ``tmux_session`` of the listing wrapper, never one derived from an id (CLAUDE.md gotcha 4b), and
``=`` makes tmux match it exactly.

PANE SIZE. The server sizes every pane itself: ``window-size manual`` plus ``resize-window`` (see
``src/core/tmux_backend.py``, set on every session it creates or adopts), so only the web view's size
negotiation moves it. Under ``manual`` an attached client never changes the window: a small ssh terminal shows
the top-left of a larger pane and the browser's pane keeps its size (proven in tests/tui/test_session_actions.py,
including after the terminal resizes). The client also attaches with the flag ``ignore-size``, so it never
counts toward the size if another client or a session option change would make tmux compute one; the TUI sets
no session option itself, because the server owns them.

SEEING THE BOTTOM OF THE PANE. claude's input box and any permission prompt sit at the bottom of the pane, so
before a suspended attach the client reads the pane's size and asks the terminal to match it with the xterm
window op ``ESC [ 8 ; rows ; cols t`` (Terminal.app and iTerm2 honor it, others ignore it), then prints one
line: how to detach, and that closing the window leaves the session running. Offline (no server, nobody else
votes on the size) the user may instead FIT the pane to this window: the attach drops ``ignore-size`` and
chains ``resize-window -A`` after it; the web view renegotiates when the server returns.

WATCH. ``read_only`` attaches with ``-r``: only detach and switch keys work, nothing typed reaches the pane.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

import structlog

from src.core.tmux_discovery import tmux_argv_prefix
from src.tui.offline.tmux_cmd import SEP, OfflineTmuxError, pane_size_argv, run_query, window_target
from src.tui.strings import t

logger = structlog.get_logger(__name__)

IGNORE_SIZE = "ignore-size"
RESIZE_OP = "\x1b[8;{rows};{cols}t"
# could not be read
DEFAULT_PREFIX_KEY = "C-b"


@dataclass(frozen=True)
class AttachPlan:

    argvs: tuple[tuple[str, ...], ...]
    env: Mapping[str, str]
    suspend: bool
    preamble: str = ""


@dataclass(frozen=True)
class PaneSize:

    cols: int
    rows: int
    status_lines: int
    prefix_key: str

    @property
    def terminal_rows(self) -> int:
        return self.rows + self.status_lines


def _status_lines(value: str) -> int:
    return 0 if value == "off" else int(value) if value.isdigit() else 1


def parse_pane_size(out: str) -> Optional[PaneSize]:
    parts = out.strip().split(SEP)
    if len(parts) != 4 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return PaneSize(int(parts[0]), int(parts[1]), _status_lines(parts[2]), parts[3] or DEFAULT_PREFIX_KEY)


def read_pane_size(prefix: Sequence[str], tmux_name: str) -> Optional[PaneSize]:
    try:
        return parse_pane_size(run_query(pane_size_argv(prefix, tmux_name)))
    except OfflineTmuxError as err:
        logger.info("tui_attach_pane_size_unknown", error=type(err).__name__)
        return None


def attach_preamble(size: Optional[PaneSize], *, resize_terminal: bool, read_only: bool) -> str:
    op = RESIZE_OP.format(rows=size.terminal_rows, cols=size.cols) if resize_terminal and size else ""
    line = t("tui.attach.detach_hint").replace("{prefix}", size.prefix_key if size else DEFAULT_PREFIX_KEY)
    if read_only:
        line = f"{t('tui.attach.watch_note')} {line}"
    return f"{op}{line}\r\n"


def socket_name() -> str:
    from src.config import settings
    from src.config.session import SessionConfig
    from src.core.tmux_socket_resolution import configured_tmux_socket_name

    return configured_tmux_socket_name(settings) or str(SessionConfig.model_fields["tmux_socket_name"].default)


def inside_socket(env: Mapping[str, str], socket: str) -> bool:
    value = env.get("TMUX", "")
    return bool(value) and os.path.basename(value.split(",", 1)[0]) == socket


def plan_attach(
    tmux_name: str,
    socket: str,
    env: Mapping[str, str],
    *,
    prefix: Optional[Sequence[str]] = None,
    read_only: bool = False,
    fit: bool = False,
    preamble: str = "",
) -> AttachPlan:
    target = f"={tmux_name}"
    base = tuple(prefix) if prefix is not None else tuple(tmux_argv_prefix(socket))
    if inside_socket(env, socket) and not read_only and not fit:
        return AttachPlan(
            argvs=(base + ("refresh-client", "-f", IGNORE_SIZE), base + ("switch-client", "-t", target)),
            env=dict(env),
            suspend=False,
        )
    clean = {k: v for k, v in env.items() if k != "TMUX"}
    flags = (("-r",) if read_only else ()) + (() if fit else ("-f", IGNORE_SIZE))
    argv = base + ("attach-session",) + flags + ("-t", target)
    if fit:
        argv += (";", "resize-window", "-A", "-t", window_target(tmux_name))
    return AttachPlan(argvs=(argv,), env=clean, suspend=True, preamble=preamble)


def run(plan: AttachPlan) -> int:
    if plan.preamble and sys.stdout.isatty():
        sys.stdout.write(plan.preamble)
        sys.stdout.flush()
    for argv in plan.argvs:
        rc = subprocess.run(list(argv), env=dict(plan.env), check=False).returncode
        if rc != 0:
            return rc
    return 0


def tmux_name_of(row: Mapping[str, object]) -> Optional[str]:
    name = row.get("tmux_session")
    return name if isinstance(name, str) and name else None
