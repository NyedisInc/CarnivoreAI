
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

import structlog

from src.core.agent_family_display import resolve_family_for_display
from src.core.db import table_exists
from src.core.db_models import SESSION_FAMILY_SOURCE_LAUNCHED

logger = structlog.get_logger()

BACKFILL_RAN = "ran"

BACKFILL_NO_TABLE = "no_sessions_table"

# COULD NOT EVALUATE could not be read
# could not
BACKFILL_CONFIG_UNREADABLE = "config_unreadable"

_CONFIG_AGENTS_KEY = "agents"
_CONFIG_WRAPPERS_KEY = "wrappers"

_CANDIDATE_WHERE = (
    "agent_family IS NULL AND agent_family_source = ? "
    "AND agent_type IS NOT NULL AND TRIM(agent_type) != ''"
)


@dataclass(frozen=True)
class BackfillResult:
    """What one backfill pass did, and why if it did nothing.

    Description: three outcomes rather than a count alone, because "no
      rows needed it" and "the config could not be read so none could be
      resolved" are different facts and only one of them is worth acting
      on.
    Inputs (constructor): outcome (str) - one of the module's outcome
      tokens. resolved (int) - rows given a family. left_null (int) -
      rows examined whose ``agent_type`` resolved to nothing, deliberately
      untouched. detail (str | None) - human-readable reason.
    Output: a BackfillResult instance.
    Example: backfill_launched_families(conn, wrappers=[]).resolved
    """

    outcome: str
    resolved: int = 0
    left_null: int = 0
    detail: Optional[str] = None


def _config_path() -> Optional[Path]:
    """Locate ``config.json`` without importing :mod:`src.config` at module load.

    Description: same shape, and the same reasons, as
      the retired ``message_archive_flag._config_path`` - the precedent for
      a migration step reading config at all. :mod:`src.config` imports
      from :mod:`src.core`, so a module-level import here would close an
      import cycle; and it calls ``sys.exit`` when ``.env`` is missing,
      which a migration must never be able to trigger.
    Inputs: none.
    Output: Path, or None when the settings object could not be built -
      reported as could-not-determine, never as "no wrappers".
    Example: _config_path() -> PosixPath('/Users/x/.../config.json')
    """
    try:
        from src.config import settings
    except (ImportError, SystemExit):
        return None
    raw = getattr(settings, "auth_config_file", None)
    if not raw:
        return None
    return Path(raw).expanduser()


def configured_wrappers(
    config_path: Optional[Path] = None,
) -> Optional[List[Any]]:
    """The wrapper list from config.json, or None when it could not be read.

    Description: reads the raw JSON rather than going through
      ``Settings.load_auth_config``, so a block that fails validation
      cannot abort a migration.
      ``resolve_family_for_display`` accepts wrapper-shaped DICTS as well
      as parsed objects, which is exactly why raw is enough here.

      NONE AND ``[]`` ARE DIFFERENT ANSWERS. ``[]`` means the file was
      read and configures no wrappers, under which a bare family name
      still resolves. None means the file could not be read at all, and
      the caller declines to write anything.
    Inputs: config_path (Path | None) - override for tests; None resolves
      it from :class:`src.config.Settings`.
    Output: list | None.
    Raises: nothing.
    Example: configured_wrappers(tmp_path / "config.json") -> [{...}]
    """
    path = config_path if config_path is not None else _config_path()
    if path is None or not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    agents = data.get(_CONFIG_AGENTS_KEY)
    if not isinstance(agents, dict):
        return []
    wrappers = agents.get(_CONFIG_WRAPPERS_KEY)
    if not isinstance(wrappers, list):
        return []
    return wrappers


def backfill_launched_families(
    conn: sqlite3.Connection, *, wrappers: Optional[List[Any]]
) -> BackfillResult:
    """Write the resolvable family onto launched rows that carry none.

    Description: selects rows whose ``agent_family`` is NULL and whose
      ``agent_family_source`` is ``launched`` - the source that asserts
      the app itself ran the agent - and resolves each row's
      ``agent_type`` through the DISPLAY resolver. A row that resolves is
      updated; a row that does not is counted and left NULL. Never
      raises for a row it cannot answer for, and never writes a family
      onto a row that already has one.
    Inputs: conn (sqlite3.Connection) - inside the caller's transaction.
      wrappers (list | None) - configured wrappers, or None meaning the
      config could not be read, in which case NOTHING is written.
    Output: BackfillResult.
    Example: backfill_launched_families(conn, wrappers=[]).outcome -> 'ran'
    """
    if not table_exists(conn, "sessions"):
        return BackfillResult(
            outcome=BACKFILL_NO_TABLE,
            detail="this database has no sessions table",
        )
    if wrappers is None:
        logger.warning(
            "session_family_backfill_config_unreadable",
            note=(
                "config.json could not be read, so a wrapper id could not "
                "be resolved to a family. Nothing is written; every row "
                "keeps its NULL, which reads the same as it did before"
            ),
        )
        return BackfillResult(
            outcome=BACKFILL_CONFIG_UNREADABLE,
            detail="config.json could not be read",
        )
    rows = conn.execute(
        f"SELECT id, agent_type FROM sessions WHERE {_CANDIDATE_WHERE}",
        (SESSION_FAMILY_SOURCE_LAUNCHED,),
    ).fetchall()

    resolved = 0
    left_null = 0
    for row in rows:
        family, _source = resolve_family_for_display(row["agent_type"], wrappers)
        if family is None:
            left_null += 1
            continue
        conn.execute(
            "UPDATE sessions SET agent_family = ? "
            "WHERE id = ? AND agent_family IS NULL",
            (family.name, int(row["id"])),
        )
        resolved += 1

    logger.info(
        "session_family_backfill",
        examined=len(rows),
        resolved=resolved,
        left_null=left_null,
        note=(
            "a row left null names a wrapper config no longer carries; "
            "null is the honest answer and a guess would be permanent"
        ),
    )
    return BackfillResult(
        outcome=BACKFILL_RAN, resolved=resolved, left_null=left_null
    )


def run_backfill(
    conn: sqlite3.Connection, *, config_path: Optional[Path] = None
) -> BackfillResult:
    if not table_exists(conn, "sessions"):
        return BackfillResult(
            outcome=BACKFILL_NO_TABLE,
            detail="this database has no sessions table",
        )
    pending = conn.execute(
        f"SELECT 1 FROM sessions WHERE {_CANDIDATE_WHERE} LIMIT 1",
        (SESSION_FAMILY_SOURCE_LAUNCHED,),
    ).fetchone()
    if pending is None:
        return BackfillResult(outcome=BACKFILL_RAN)
    return backfill_launched_families(
        conn, wrappers=configured_wrappers(config_path)
    )
