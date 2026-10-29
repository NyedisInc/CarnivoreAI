
from __future__ import annotations

import sqlite3
import time
from typing import Optional

import structlog

from src.core.db import get_meta, set_meta
from src.core.db_models import META_STAGE_A_BOUNDARY_EPOCH

logger = structlog.get_logger()


def read_boundary(conn: sqlite3.Connection) -> Optional[int]:
    raw = get_meta(conn, META_STAGE_A_BOUNDARY_EPOCH)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.error(
            "stage_a_boundary_unparseable",
            raw=str(raw)[:100],
            note=(
                "the Stage-A boundary stamp is present but is not an "
                "integer epoch, so whether a CLOUDECODE_ORIGIN marker is "
                "admissible CANNOT BE DETERMINED; tier 4 is disabled "
                "rather than defaulted"
            ),
        )
        return None
    if value < 0:
        logger.error("stage_a_boundary_negative", raw=value)
        return None
    return value


def record_boundary(
    conn: sqlite3.Connection, *, now_epoch: Optional[int] = None
) -> int:
    existing = read_boundary(conn)
    if existing is not None:
        return existing
    value = int(now_epoch if now_epoch is not None else time.time())
    set_meta(conn, META_STAGE_A_BOUNDARY_EPOCH, str(value))
    logger.info(
        "stage_a_boundary_recorded",
        epoch=value,
        note=(
            "every tmux session older than this predates the create-path "
            "write site on this install, so a CLOUDECODE_ORIGIN marker on "
            "one of them is ignored"
        ),
    )
    return value
