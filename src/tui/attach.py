
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
