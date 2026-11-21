
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
from typing import List, Optional

import structlog

from src.core.pack.jobs import boot
from src.core.pack.jobs.types import JobError

log = structlog.get_logger(__name__)

LAUNCH_LINE = ("this project has auto-delegate on: delegate heavy work (builds, tests, renders, browsers, long runs) by calling the carnivore "
               "delegate tool first; it answers run-it-here at once when this computer has room. everything else runs here. new agents and subagents go to "
               "the computer with room: agent_spawn starts on one by default (placement auto), and when a subagent is refused with a computer named, run it "
               "through the delegate tool as an agent task instead.")
FLAG = "--append-system-prompt"
HOOK_SCRIPT = Path(__file__).with_name("precheck_hook.py")


def line_for(working_dir: Optional[str]) -> Optional[str]:
    if not working_dir:
        return None
    try:
        engine = boot.engine()
        uids = engine.store.marked_projects()
        if not uids:
            return None
        real = os.path.realpath(working_dir)
        marks = ",".join("?" for _ in uids)
        with closing(engine._open_db()) as conn:  # noqa: SLF001
            roots = [r[0] for r in conn.execute(
                f"SELECT root FROM projects WHERE host_key = 'local' AND archived_at IS NULL AND uid IN ({marks})", uids)]
    except JobError:
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("launch_line_unreadable", error_type=type(exc).__name__, error=str(exc))
        return None
    for root in roots:
        top = os.path.realpath(root).rstrip("/")
        if real == top or real.startswith(top + "/"):
            return LAUNCH_LINE
    return None


def add_to_args(args: List[str], line: str) -> List[str]:
    for i, a in enumerate(args[:-1]):
        if a == FLAG:
            if line in args[i + 1]:
                return list(args)
            return [*args[:i + 1], f"{args[i + 1]}\n{line}", *args[i + 2:]]
    return [*args, FLAG, line]
