
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Optional

from src.core.db import (
    DatastoreUnreadableError,
    connect,
    db_path_for,
    get_schema_version,
)
from src.core.db_integrity_status import cached_failure_detail
from src.core.db_state import (
    CANNOT_DETERMINE,
    STATUS_DEGRADED_DB_UNREADABLE,
    TRAIL_STATUS_UNREADABLE,
    DatastoreState,
)

STATUS_NOT_RESOLVED = "not_resolved"


def unresolved_state(code_schema_version: int) -> DatastoreState:
    return DatastoreState(
        status=STATUS_NOT_RESOLVED,
        schema_version=CANNOT_DETERMINE,
        config_version=CANNOT_DETERMINE,
        trail_status=TRAIL_STATUS_UNREADABLE,
        code_schema_version=code_schema_version,
        message=(
            "the datastore was not resolved in this process, so its state "
            "is unknown - this is not a claim that it is healthy."
        ),
    )


def live_state(startup_state: Optional[DatastoreState], state_dir: Path,
               code_schema_version: int) -> DatastoreState:
    if startup_state is None:
        startup_state = unresolved_state(code_schema_version)

    db_path = db_path_for(state_dir)
    try:
        with closing(connect(db_path, create=False)) as conn:
            found = get_schema_version(conn)
    except DatastoreUnreadableError as exc:
        return _unreachable(
            startup_state,
            db_path,
            str(exc),
            "cloude.db is UNREACHABLE. This is not an empty database and it "
            "is not an install with no data - the file the app's state lives "
            "in could not be opened.",
        )
    except Exception as exc:  # noqa: BLE001
        return _unreachable(
            startup_state, db_path, f"{type(exc).__name__}: {exc}",
            "cloude.db could not be probed.",
        )

    failure = cached_failure_detail(state_dir)
    if failure is not None:
        return _unreachable(
            startup_state,
            db_path,
            f"PRAGMA integrity_check: {failure}",
            "cloude.db failed its integrity check. Nothing it would report "
            "can be trusted, so nothing is being reported as healthy.",
        )

    if isinstance(startup_state.schema_version, int) or startup_state.healthy:
        startup_state.schema_version = found
    return startup_state


def _unreachable(
    startup_state: DatastoreState, db_path: Path, detail: str, message: str
) -> DatastoreState:
    return DatastoreState(
        status=STATUS_DEGRADED_DB_UNREADABLE,
        schema_version=CANNOT_DETERMINE,
        config_version=startup_state.config_version,
        trail_status=startup_state.trail_status,
        code_schema_version=startup_state.code_schema_version,
        message=message,
        detail=detail,
        trail_corrupt_line=startup_state.trail_corrupt_line,
        last_migration_at=startup_state.last_migration_at,
        db_path=str(db_path),
    )
