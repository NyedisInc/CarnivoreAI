
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

import structlog

from src.core.safe_io.readonly_db import connect_readonly
from src.core.pack.jobs import ddl
from src.core.pack.jobs.types import JobState
from src.models.session_token_usage import DelegatedUsage

logger = structlog.get_logger()

MAX_COUNT = 1e12


RUNNING_ON_PEER = tuple(s.value for s in (JobState.MIRRORING, JobState.STARTING, JobState.RUNNING, JobState.COLLECTING, JobState.LANDING))


def _count(value: object) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= MAX_COUNT
    return float(value) if ok else 0.0


def delegated_for(session_id: Optional[str], session_uuid: Optional[str], *, state_dir: Optional[Path] = None) -> Optional[DelegatedUsage]:
    keys = [k for k in (session_uuid, session_id) if k]
    if not keys:
        return None
    if state_dir is None:
        from src.config import settings

        state_dir = settings.get_state_dir()
    db_file = Path(state_dir) / ddl.FILENAME
    if not db_file.is_file():
        return None
    marks = ",".join("?" for _ in keys)
    try:
        with closing(connect_readonly(db_file, timeout=5)) as conn:
            rows = conn.execute(
                f"SELECT usage_json, account_label FROM jobs WHERE body = 'agent' AND usage_json IS NOT NULL AND caller_session IN ({marks})",
                keys).fetchall()
            placed = conn.execute(
                f"SELECT peer_label FROM jobs WHERE peer_install_id IS NOT NULL AND caller_session IN ({marks})", keys).fetchall()
            live = conn.execute(
                f"SELECT peer_label FROM jobs WHERE peer_install_id IS NOT NULL AND state IN ({','.join('?' for _ in RUNNING_ON_PEER)}) "
                f"AND caller_session IN ({marks})", (*RUNNING_ON_PEER, *keys)).fetchall()
    except sqlite3.Error as exc:
        logger.info("pack_jobs_usage_rollup_unreadable", error_type=type(exc).__name__)
        return None
    totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    cost: Optional[float] = None
    accounts: list[str] = []
    jobs = 0
    for usage_json, label in rows:
        try:
            usage = json.loads(usage_json)
        except ValueError:
            continue
        if not isinstance(usage, dict):
            continue
        jobs += 1
        for key in totals:
            value = usage.get(key)
            totals[key] += int(_count(value))
        usd = usage.get("cost_usd")
        if isinstance(usd, (int, float)) and not isinstance(usd, bool) and math.isfinite(usd) and 0 <= usd <= MAX_COUNT:
            cost = (cost or 0.0) + float(usd)
        if label and label not in accounts:
            accounts.append(str(label))
    running_on = list(dict.fromkeys(str(label) for (label,) in live if label))
    ran_on = list(dict.fromkeys(str(label) for (label,) in placed if label))
    if jobs == 0 and not live and not placed:
        return None
    return DelegatedUsage(jobs=jobs, remote_jobs=len(placed), ran_on=ran_on, cost_usd=cost, accounts=accounts, running=len(live), running_on=running_on, **totals)
