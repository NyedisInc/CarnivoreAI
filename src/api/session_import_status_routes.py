
from fastapi import APIRouter, Depends, Request
from src.api.auth import require_auth
from src.config import settings
from src.models import SessionImportStatus

from fastapi.concurrency import run_in_threadpool

router = APIRouter()


@router.get(
    "/sessions/import-status",
    response_model=SessionImportStatus,
    dependencies=[Depends(require_auth)],
)
async def session_import_status(request: Request):
    """Whether the one-way first-run session import has run, and if not why.

    Description: THE THIRD OUTCOME MADE VISIBLE. The import is guarded by
      ``meta.imported_from_json_at``, a latch stamped once and never
      cleared, over an input (the live tmux process list) that is gone by
      tomorrow. If the tmux probe fails, the import writes NOTHING and
      leaves the latch unset - correct, but invisible, because an empty
      RECENT list looks exactly like a user with no history. This route is
      how that silence gets a voice: ``pending`` with the probe's own
      reason, and a ``notice`` sentence for the home screen.

      ``unavailable`` is its own state and is never folded into either of
      the other two: a datastore we could not read tells us nothing about
      whether the import ran.
    Inputs: request (Request) - unused beyond auth.
    Output: SessionImportStatus.
    """
    from contextlib import closing


    from src.core import session_store
    from src.core.db import DatastoreUnreadableError, connect, db_path_for, get_meta
    from src.core.db_models import (
        META_IMPORTED_FROM_JSON_AT,
        META_SESSION_IMPORT_PENDING_REASON,
    )

    db_path = db_path_for(settings.get_state_dir())
    if not db_path.exists():
        return SessionImportStatus(
            state="pending",
            pending_reason="datastore_absent",
            notice=(
                "Session import is PENDING: the datastore has not been "
                "created yet. No sessions were imported and none were lost."
            ),
        )

    def _read() -> tuple:
        with closing(connect(db_path, create=False)) as conn:
            return (
                get_meta(conn, META_IMPORTED_FROM_JSON_AT),
                get_meta(conn, META_SESSION_IMPORT_PENDING_REASON),
                session_store.count_sessions(conn),
            )

    try:
        imported_at, pending_reason, count = await run_in_threadpool(_read)
    except DatastoreUnreadableError as exc:
        return SessionImportStatus(
            state="unavailable",
            notice=(
                "Session import state CANNOT BE DETERMINED: the datastore "
                f"could not be read ({exc}). This is not a report that the "
                "import did or did not run."
            ),
        )

    if imported_at:
        return SessionImportStatus(
            state="completed", imported_at=imported_at, session_count=count
        )

    reason = pending_reason or "not_yet_run"
    return SessionImportStatus(
        state="pending",
        pending_reason=reason,
        session_count=count,
        notice=(
            "Session import is PENDING: tmux could not be listed "
            f"(reason: {reason}). No sessions were imported and none were "
            "lost. This retries automatically on the next start."
        ),
    )
