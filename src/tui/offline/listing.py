
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

from src.core.product_identity import is_owned_session_name
from src.core.tmux_listing_parse import is_plumbing_session
from src.tui.offline.names import read_names
from src.tui.offline.tmux_cmd import SEP, TmuxTarget, list_panes_argv, list_sessions_argv, run_query

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OfflineRow:

    tmux_name: str
    created_epoch: Optional[int]
    attached: int
    dead: bool
    owned: bool
    display_name: Optional[str] = None
    project: Optional[str] = None

    @property
    def attachable(self) -> bool:
        return not self.dead


def _int(text: str) -> Optional[int]:
    return int(text) if text.isdigit() else None


def parse_sessions(out: str) -> list[tuple[str, str, Optional[int], int]]:
    parsed = []
    for line in out.splitlines():
        parts = line.split(SEP, 3)
        if len(parts) != 4 or not parts[3]:
            logger.debug("tui_offline_skip_session_line")
            continue
        sid, created, attached, name = parts
        if is_plumbing_session(name):
            continue
        parsed.append((sid, name, _int(created), _int(attached) or 0))
    return parsed


def dead_sessions(out: str) -> set[str]:
    alive: set[str] = set()
    seen: set[str] = set()
    for line in out.splitlines():
        parts = line.split(SEP)
        if len(parts) < 2:
            continue
        seen.add(parts[0])
        if parts[1] != "1":
            alive.add(parts[0])
    return seen - alive


def list_rows(target: TmuxTarget, state_dir: Optional[Path], show_all: bool) -> list[OfflineRow]:
    sessions = parse_sessions(run_query(list_sessions_argv(target)))
    dead = dead_sessions(run_query(list_panes_argv(target)))
    names = read_names(state_dir, target.socket_name, [(name, created) for _sid, name, created, _att in sessions])
    rows = []
    for sid, name, created, attached in sessions:
        owned = is_owned_session_name(name)
        if not owned and not show_all:
            continue
        known = names.get(name)
        rows.append(
            OfflineRow(
                tmux_name=name, created_epoch=created, attached=attached, dead=sid in dead, owned=owned,
                display_name=known.display_name if known else None, project=known.project if known else None,
            )
        )
    rows.sort(key=lambda row: (not row.owned, (row.display_name or row.tmux_name).lower()))
    return rows
