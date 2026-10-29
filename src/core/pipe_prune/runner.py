
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Callable, Optional

import structlog

from src.core.pipe_prune.gather import open_files_among, read_panes
from src.core.pipe_prune.plan import (
    Decision,
    PaneFacts,
    Refusal,
    Verdict,
    is_prunable_shape,
    plan_prune,
    refusal_for,
)

logger = structlog.get_logger()

FIRST_PASS_DELAY_SECONDS: float = 600.0

INTERVAL_SECONDS: float = 6 * 3600.0


def ladder_consumed(state_dir: Path) -> bool:
    from src.core.db import DatastoreError, connect, db_path_for
    from src.core.session_import import (
        EVIDENCE_LADDER_VERSION,
        ImportLatchUnreadable,
        sessions_stage_version,
    )

    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            version = sessions_stage_version(conn)
    except (ImportLatchUnreadable, DatastoreError, sqlite3.Error, OSError) as exc:
        logger.warning("pipe_prune_ladder_state_unreadable", error=str(exc))
        return False
    return version is not None and version >= EVIDENCE_LADDER_VERSION


def prune_once(
    log_dir: Path,
    *,
    socket_name: str,
    ladder_done: bool,
    min_age_seconds: float,
    now: Optional[float] = None,
    read_panes_fn: Callable[[str], PaneFacts] = read_panes,
    open_files_fn: Callable = open_files_among,
) -> dict:
    when = time.time() if now is None else now
    try:
        files = sorted(p for p in Path(log_dir).iterdir() if is_prunable_shape(p))
    except OSError as exc:
        logger.warning("pipe_prune_dir_unreadable", log_dir=str(log_dir), error=str(exc))
        return {"refused": "log_dir_unreadable", "pruned": 0, "reclaimed_bytes": 0, "kept": 0}
    facts = read_panes_fn(socket_name)
    open_paths = open_files_fn(files)
    refusal = refusal_for(facts, ladder_done, open_paths)
    if refusal is not None:
        logger.info("pipe_prune_refused", reason=refusal.value, candidates=len(files))
        return {"refused": refusal.value, "pruned": 0, "reclaimed_bytes": 0, "kept": len(files)}

    pruned = reclaimed = kept = 0
    for decision in plan_prune(files, facts, open_paths, when, min_age_seconds):
        if decision.verdict is not Verdict.PRUNE:
            kept += 1
            continue
        if _delete(decision):
            pruned += 1
            reclaimed += decision.size
        else:
            kept += 1
    logger.info("pipe_prune_pass", pruned=pruned, kept=kept, reclaimed_bytes=reclaimed)
    return {"refused": None, "pruned": pruned, "reclaimed_bytes": reclaimed, "kept": kept}


def _delete(decision: Decision) -> bool:
    try:
        decision.path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("pipe_orphan_prune_failed", file=decision.path.name, error=str(exc))
        return False
    logger.info(
        "pipe_orphan_pruned",
        file=decision.path.name,
        size_bytes=decision.size,
        age_hours=round(decision.age_hours, 1),
    )
    return True


class PipePruner:

    def __init__(self, *, log_dir: Path, state_dir: Path, socket_name: str) -> None:
        self._log_dir = log_dir
        self._state_dir = state_dir
        self._socket = socket_name

    async def run(self) -> None:
        from src.core.tmux_backend import ROTATE_AGE_HOURS

        delay = FIRST_PASS_DELAY_SECONDS
        while True:
            try:
                await asyncio.sleep(delay)
                delay = INTERVAL_SECONDS
                await asyncio.to_thread(self._pass, ROTATE_AGE_HOURS * 3600.0)
            except asyncio.CancelledError:
                raise
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                logger.warning("pipe_prune_pass_failed", error=str(exc))

    def _pass(self, min_age_seconds: float) -> dict:
        return prune_once(
            self._log_dir,
            socket_name=self._socket,
            ladder_done=ladder_consumed(self._state_dir),
            min_age_seconds=min_age_seconds,
        )
