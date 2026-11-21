
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

from src.core.safe_io.readonly_db import connect_readonly
from src.core.pack.jobs import ddl

logger = structlog.get_logger()

_LIVE_STATES = ("preparing", "running", "parked")


@dataclass(frozen=True)
class SlotHit:

    project_uid: str
    job_id: str
    slot_path: str


def jobs_root_real() -> str:
    from src.core.pack.jobs.paths import default_jobs_root

    return os.path.realpath(os.fspath(default_jobs_root()))


def is_within(folder: str, root: str) -> bool:
    return folder == root or folder.startswith(root.rstrip(os.sep) + os.sep)


def in_jobs_root(folder: str) -> bool:
    return is_within(os.path.realpath(folder), jobs_root_real())


def live_agent_slot(folder: str, *, state_dir: Optional[Path] = None) -> Optional[SlotHit]:
    target = os.path.realpath(folder)
    if not is_within(target, jobs_root_real()):
        return None
    if state_dir is None:
        from src.config import settings

        state_dir = settings.get_state_dir()
    db_file = Path(state_dir) / ddl.FILENAME
    if not db_file.is_file():
        return None
    marks = ",".join("?" for _ in _LIVE_STATES)
    try:
        with closing(connect_readonly(db_file, timeout=5)) as conn:
            rows = conn.execute(
                f"SELECT s.path, s.project_uid, s.job_id FROM slots s JOIN host_jobs h ON h.job_id = s.job_id "
                f"WHERE h.body = 'agent' AND h.state IN ({marks})", _LIVE_STATES).fetchall()
    except sqlite3.Error as exc:
        logger.info("pack_jobs_slot_lookup_unreadable", error_type=type(exc).__name__)
        return None
    for path, project_uid, job_id in rows:
        real = os.path.realpath(str(path))
        if is_within(target, real):
            return SlotHit(project_uid=str(project_uid), job_id=str(job_id), slot_path=real)
    return None
