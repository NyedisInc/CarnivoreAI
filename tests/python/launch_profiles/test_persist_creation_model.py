
from __future__ import annotations

from src.core.session_create_persist import persist_creation
from src.core.tmux_listing import TmuxListing
from tests.lifecycle_helpers import conn  # noqa: F401


def _listing(name: str) -> TmuxListing:
    return TmuxListing.answered(
        [{"name": name, "created_at_epoch": 5000, "session_id": "$4", "window_count": 1}]
    )


def _model(conn, name: str):
    return conn.execute(
        "SELECT model FROM sessions WHERE tmux_name = ?", (name,)
    ).fetchone()["model"]


def test_create_persists_the_launch_model(conn):
    with_model = persist_creation(
        conn, socket="cloude", name="cloude_m", listing=_listing("cloude_m"),
        agent_type="claude", agent_launched=True, model="qwen3-coder",
    )
    without = persist_creation(
        conn, socket="cloude", name="cloude_n", listing=_listing("cloude_n"),
        agent_type="claude", agent_launched=True,
    )
    assert with_model.recorded and without.recorded
    assert _model(conn, "cloude_m") == "qwen3-coder"
    assert _model(conn, "cloude_n") is None
