
from __future__ import annotations

from tests.lifecycle_helpers import conn  # noqa: F401

from src.api.session_record_payload import _session_record_payload
from src.core.session_create_persist import persist_creation
from src.core.session_store import list_sessions
from src.core.tmux_listing import TmuxListing

SOCKET = "cloude"


def listing_for(name: str, *, epoch: int) -> TmuxListing:
    return TmuxListing.answered(
        [{"name": name, "created_at_epoch": epoch, "session_id": "$9", "window_count": 1}]
    )


def _add_project(conn, *, display_name: str, root: str) -> int:
    cur = conn.execute(
        "INSERT INTO projects (root, raw_path, display_name, source, "
        "created_at, updated_at) VALUES (?, ?, ?, 'test', "
        "'2026-09-25T00:00:00Z', '2026-09-25T00:00:00Z')",
        (root, root, display_name),
    )
    conn.commit()
    return int(cur.lastrowid)


def _bind(conn, *, name: str, project_id) -> None:
    conn.execute(
        "UPDATE sessions SET project_id = ? WHERE tmux_name = ?",
        (project_id, name),
    )
    conn.commit()


def _sleep(conn, *, name: str) -> None:
    conn.execute(
        "UPDATE sessions SET lifecycle = 'stopped', "
        "lifecycle_source = 'slept_by_user' WHERE tmux_name = ?",
        (name,),
    )
    conn.commit()


def _persist(conn, name: str, epoch: int) -> None:
    persist_creation(
        conn,
        socket=SOCKET,
        name=name,
        listing=listing_for(name, epoch=epoch),
        agent_type="claude",
        agent_family="claude",
        agent_launched=True,
    )


def _row_by_name(rows, name: str) -> dict:
    matches = [r for r in rows if r.get("tmux_name") == name]
    assert len(matches) == 1, f"expected exactly one row for {name!r}, got {matches}"
    return matches[0]




def test_an_asleep_rows_wire_payload_carries_its_project_name(conn):
    _persist(conn, "carnivore_bound", 8100)
    pid = _add_project(conn, display_name="Quartzline", root="/tmp/quartzline")
    _bind(conn, name="carnivore_bound", project_id=pid)
    _sleep(conn, name="carnivore_bound")

    rows = list_sessions(conn)
    row = _row_by_name(rows, "carnivore_bound")
    assert row["project_id"] == pid
    assert row["project_name"] == "Quartzline", (
        "an asleep session's project name must reach the wire the same "
        "way its project_id already does - without it the sidebar files "
        "the row under 'unnamed project'"
    )

    payload = _session_record_payload(row)
    assert payload.project_id == pid
    assert payload.project_name == "Quartzline"
    assert payload.asleep is True




def test_an_unbound_session_reports_no_project_name_rather_than_guessing(conn):
    _persist(conn, "carnivore_loose", 8200)
    _bind(conn, name="carnivore_loose", project_id=None)

    rows = list_sessions(conn)
    row = _row_by_name(rows, "carnivore_loose")
    assert row["project_id"] is None
    assert row["project_name"] is None




def test_a_missing_projects_table_costs_the_project_not_the_listing(conn):
    _persist(conn, "carnivore_nomigrate", 8300)
    conn.execute("DROP TABLE projects")
    conn.commit()

    rows = list_sessions(conn)
    row = _row_by_name(rows, "carnivore_nomigrate")
    assert row is not None, "a missing projects table must not fail the read"
    assert row["agent_type"] == "claude"
    assert row["project_id"] is None
    assert row["project_name"] is None
