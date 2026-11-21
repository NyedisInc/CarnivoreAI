
from __future__ import annotations

from src.core.db import transaction
from src.core.mcp.session_target import _row_has_id
from src.core.session_create_persist import persist_creation
from src.core.tmux_listing import TmuxListing
from tests.lifecycle_helpers import conn  # noqa: F401

NAME = "carnivore_scratch"
APP_ID = "ses_53050463"


def _listing(epoch: int, sid: str) -> TmuxListing:
    return TmuxListing.answered([{"name": NAME, "created_at_epoch": epoch, "session_id": sid, "window_count": 1}])


def _create(conn, *, epoch: int = 5000, sid: str = "$4", **kwargs):
    with transaction(conn):
        return persist_creation(conn, socket="cloude", name=NAME, listing=_listing(epoch, sid),
                                working_dir="/tmp/x", **kwargs)


def _row(conn) -> dict:
    return dict(conn.execute("SELECT * FROM sessions WHERE tmux_name = ?", (NAME,)).fetchone())


def test_a_created_row_resolves_by_its_ses_id_after_exit(conn):
    assert _create(conn, app_session_id=APP_ID).recorded
    with transaction(conn):
        conn.execute("UPDATE sessions SET lifecycle = 'stopped' WHERE tmux_name = ?", (NAME,))
    row = _row(conn)
    assert row["legacy_session_id"] == APP_ID
    assert _row_has_id(row, APP_ID)


def test_a_non_app_id_is_never_stored(conn):
    assert _create(conn, app_session_id="adopted:carnivore_scratch").recorded
    assert _row(conn)["legacy_session_id"] is None


def test_a_restart_that_reuses_the_row_stores_the_new_ses_id(conn):
    _create(conn, app_session_id="ses_00000001")
    row_id = _row(conn)["id"]
    with transaction(conn):
        conn.execute("UPDATE sessions SET lifecycle = 'stopped' WHERE id = ?", (row_id,))
    assert _create(conn, epoch=6000, sid="$9", reuse_session_id=row_id, app_session_id=APP_ID).recorded
    row = _row(conn)
    assert row["id"] == row_id
    assert _row_has_id(row, APP_ID)
