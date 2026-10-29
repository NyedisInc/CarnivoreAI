
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, Optional

import structlog

from src.core.pipe_liveness import PIPE_OWNER_OPTION
from src.core.pipe_prune.plan import PaneFacts
from src.core.tmux_discovery import resolve_tmux_path, tmux_argv_prefix

logger = structlog.get_logger()

PROBE_TIMEOUT_SECONDS: float = 20.0

PANE_FORMAT: str = "#{session_name}\t#{" + PIPE_OWNER_OPTION + "}"


def parse_pane_rows(text: str) -> PaneFacts:
    """Parse ``list-panes -a`` output into facts. PURE.

    Description: a row without the tab separator, or with an empty session
      name, makes the whole answer incomplete: a row we could not read may
      have been the session that owns a file.
    Inputs: text (str) - stdout of the pane listing.
    Output: PaneFacts.
    Example: parse_pane_rows("cloude_a\\t/x/tmux_cloude_a.pipe\\n").complete
    """
    names: set[str] = set()
    owners: set[str] = set()
    for row in text.split("\n"):
        if not row:
            continue
        name, sep, owner = row.partition("\t")
        if not sep or not name:
            return PaneFacts(complete=False)
        names.add(name)
        if owner.strip():
            owners.add(owner.strip())
    return PaneFacts(True, frozenset(names), frozenset(owners))


def read_panes(socket_name: str) -> PaneFacts:
    if resolve_tmux_path() is None:
        return PaneFacts(complete=False)
    argv = tmux_argv_prefix(socket_name) + ["list-panes", "-a", "-F", PANE_FORMAT]
    try:
        proc = subprocess.run(
            argv, capture_output=True, timeout=PROBE_TIMEOUT_SECONDS, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("pipe_prune_tmux_probe_failed", error=str(exc))
        return PaneFacts(complete=False)
    if proc.returncode != 0:
        return PaneFacts(complete=False)
    return parse_pane_rows(proc.stdout.decode("utf-8", errors="replace"))


def open_files_among(paths: Iterable[Path]) -> Optional[frozenset]:
    targets = [os.path.realpath(p) for p in paths]
    if not targets:
        return frozenset()
    try:
        proc = subprocess.run(
            ["lsof", "-F", "n", "--", *targets],
            capture_output=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("pipe_prune_lsof_failed", error=str(exc))
        return None
    if proc.returncode not in (0, 1):
        return None
    lines = proc.stdout.decode("utf-8", errors="replace").split("\n")
    return frozenset(
        os.path.realpath(line[1:]) for line in lines if line.startswith("n")
    )
