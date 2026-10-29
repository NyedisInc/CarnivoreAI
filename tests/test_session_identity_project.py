
from __future__ import annotations

from tests.lifecycle_helpers import ROOT, conn  # noqa: F401

from src.core.session_create_persist import persist_creation
from src.core.session_store import identity_for_live_name
from src.core.tmux_listing import TmuxListing

SOCKET = "cloude"


def listing_for(name: str, *, epoch: int) -> TmuxListing:
    return TmuxListing.answered(
        [
            {
                "name": name,
                "created_at_epoch": epoch,
                "session_id": "$9",
                "window_count": 1,
            }
        ]
    )


def _add_project(conn, *, display_name: str, root: str) -> int:
    cur = conn.execute(
        "INSERT INTO projects (root, raw_path, display_name, source, "
        "created_at, updated_at) VALUES (?, ?, ?, 'test', "
        "'2026-09-22T00:00:00Z', '2026-09-22T00:00:00Z')",
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


def _persist(conn, name: str, epoch: int) -> None:
    persist_creation(
        conn,
        socket=SOCKET,
        name=name,
        listing=listing_for(name, epoch=epoch),
        agent_type="codex-yolo",
        agent_family="codex",
        agent_launched=True,
    )




def test_a_bound_session_carries_its_project_id_and_name(conn):
    _persist(conn, "cloude_bound", 7200)
    pid = _add_project(conn, display_name="Fenford FIRFORD", root="/tmp/ravcrest-ravvale")
    _bind(conn, name="cloude_bound", project_id=pid)

    row = identity_for_live_name(conn, socket=SOCKET, name="cloude_bound")
    assert row["project_id"] == pid
    assert row["project_name"] == "Fenford FIRFORD"
    assert row["agent_type"] == "codex-yolo"
    assert row["agent_family"] == "codex"




def test_an_unbound_session_reports_no_project_rather_than_guessing(conn):
    _persist(conn, "cloude_loose", 7300)
    _bind(conn, name="cloude_loose", project_id=None)

    row = identity_for_live_name(conn, socket=SOCKET, name="cloude_loose")
    assert row["project_id"] is None
    assert row["project_name"] is None
    assert row["agent_type"] == "codex-yolo"




def test_a_missing_projects_table_costs_the_project_not_the_identity(conn):
    _persist(conn, "cloude_nomigrate", 7500)
    conn.execute("DROP TABLE projects")
    conn.commit()

    row = identity_for_live_name(conn, socket=SOCKET, name="cloude_nomigrate")
    assert row is not None, "a missing projects table must not fail the read"
    assert row["agent_type"] == "codex-yolo"
    assert row["agent_family"] == "codex"
    assert row["project_id"] is None
    assert row["project_name"] is None




def test_the_conversation_id_is_present_when_known_and_none_when_not(conn):
    from src.models.sessions import SessionInfo

    _persist(conn, "cloude_known", 7300)
    _persist(conn, "cloude_unknown", 7301)
    conn.execute(
        "UPDATE sessions SET claude_session_uuid = ? WHERE tmux_name = ?",
        ("11111111-2222-3333-4444-555555555555", "cloude_known"),
    )
    conn.commit()

    known = identity_for_live_name(conn, socket=SOCKET, name="cloude_known")
    unknown = identity_for_live_name(conn, socket=SOCKET, name="cloude_unknown")
    assert known["claude_session_uuid"] == "11111111-2222-3333-4444-555555555555"
    assert unknown["claude_session_uuid"] is None
    assert "claude_session_uuid" in SessionInfo.model_fields
    assert SessionInfo.model_fields["claude_session_uuid"].default is None
