
from __future__ import annotations

import sys

from tests.lifecycle_helpers import ROOT, conn

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402,F401

from src.core.session_create_persist import persist_creation
from src.core.tmux_listing import TmuxListing


def listing_for(name, epoch=5000, sid="$4"):
    return TmuxListing.answered(
        [
            {
                "name": name,
                "created_at_epoch": epoch,
                "session_id": sid,
                "window_count": 1,
            }
        ]
    )


def row_for(conn, name):
    row = conn.execute(
        "SELECT * FROM sessions WHERE tmux_name = ?", (name,)
    ).fetchone()
    assert row is not None, f"no row for {name}"
    return dict(row)


def test_a_create_with_a_label_writes_the_title(conn):
    result = persist_creation(
        conn,
        socket="cloude",
        name="cloude_punchlist_two",
        listing=listing_for("cloude_punchlist_two"),
        agent_type="claude",
        agent_launched=True,
        label="Punchlist Two",
    )

    assert result.recorded, result.detail
    row = row_for(conn, "cloude_punchlist_two")
    assert row["title"] == "Punchlist Two"
    assert row["claude_title"] is None


def test_a_create_with_no_label_leaves_the_title_null(conn):
    persist_creation(
        conn,
        socket="cloude",
        name="cloude_no_label",
        listing=listing_for("cloude_no_label"),
        agent_type="claude",
        agent_launched=True,
    )

    assert row_for(conn, "cloude_no_label")["title"] is None


def test_an_empty_or_blank_label_is_treated_as_no_label(conn):
    persist_creation(
        conn,
        socket="cloude",
        name="cloude_blank_label",
        listing=listing_for("cloude_blank_label"),
        agent_type="claude",
        agent_launched=True,
        label="",
    )

    assert row_for(conn, "cloude_blank_label")["title"] is None


def test_a_label_never_overwrites_an_existing_titled_row(conn):
    listing = listing_for("cloude_repeat", epoch=6000)
    persist_creation(
        conn,
        socket="cloude",
        name="cloude_repeat",
        listing=listing,
        agent_type="claude",
        agent_launched=True,
        label="Original Label",
    )

    persist_creation(
        conn,
        socket="cloude",
        name="cloude_repeat",
        listing=listing,
        agent_type="claude",
        agent_launched=True,
        label="A Different Label",
    )

    assert row_for(conn, "cloude_repeat")["title"] == "Original Label"


def test_the_reuse_path_never_lets_a_label_overwrite_the_reused_row(conn):
    first = persist_creation(
        conn,
        socket="cloude",
        name="cloude_stopped",
        listing=listing_for("cloude_stopped", epoch=7000),
        agent_type="claude",
        agent_launched=True,
        label="Kept Title",
    )
    assert first.recorded
    row_id = row_for(conn, "cloude_stopped")["id"]

    persist_creation(
        conn,
        socket="cloude",
        name="cloude_stopped",
        listing=listing_for("cloude_stopped", epoch=7001),
        agent_type="claude",
        agent_launched=True,
        reuse_session_id=row_id,
        label="Kept Title",
    )

    row = row_for(conn, "cloude_stopped")
    assert row["id"] == row_id
    assert row["title"] == "Kept Title"
