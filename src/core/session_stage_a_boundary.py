"""When did THIS install first run a build that records ``origin='created'``?

So the ladder needs a date, and this module is where the date comes from.

WHY A RECORDED STAMP RATHER THAN AN INFERENCE. The obvious alternative is
to derive the boundary from the earliest ``origin='created'`` row. That is
a guess wearing a measurement's clothes: it is wrong on an install that
has not created a session yet, wrong on one whose oldest created row was
archived, and it moves whenever the data moves. This module records the
moment instead, once, and never moves it - the same reasoning the schema
uses for the project-tombstones marker.

WHAT ABSENT MEANS, AND WHY IT IS NOT ZERO. Absent means CANNOT DETERMINE.
:func:`read_boundary` returns None and the ladder makes tier 4
INADMISSIBLE rather than assumed valid. Returning 0 would silently admit
every marker on every session ever created, which is precisely the
invented verdict the whole import exists to stop. An UNPARSEABLE value is
also None, and is logged at error - a corrupt stamp is not a valid one.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Optional

import structlog

from src.core.db import get_meta, set_meta
from src.core.db_models import META_STAGE_A_BOUNDARY_EPOCH

logger = structlog.get_logger()


def read_boundary(conn: sqlite3.Connection) -> Optional[int]:
    """The unix epoch at or after which a tier-4 marker is admissible here.

    Description: THREE OUTCOMES. A parseable stamp is the boundary; an
      absent one is None meaning "this install has no record, so tier 4
      cannot be applied"; an unparseable one is ALSO None and is logged,
      because a corrupt stamp tells us less than no stamp, not more.
    Inputs: conn (sqlite3.Connection).
    Output: int | None - None means CANNOT DETERMINE.
    Example: read_boundary(conn)  # 1755000000, or None
    """
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
