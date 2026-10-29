
from __future__ import annotations

from src.core.sessions import closed_time as session_closed_time
from src.core.db_models import SESSION_LIFECYCLE_STOPPED, SESSION_ORIGIN_OBSERVED
from src.core.session_manager import ProbeHealth
from tests.test_s9_recent_and_pills import _HealthManager, _recent_client, _routes_settings


def _seed(tmp_path):
    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.session_identity import record_instance

    ensure_db_migrated(tmp_path, 4, "test")
    conn = connect(db_path_for(tmp_path), create=True)
    try:
        plan = [
            ("mid", 3001, "2026-09-30T10:00:00Z", "tmux_missing"),
            ("last", 3002, "2026-09-30T12:00:00Z", "tmux_missing"),
            ("first", 3003, "2026-09-30T08:00:00Z", "tmux_missing"),
        ]
        for name, epoch, stamp, source in plan:
            record_instance(
                conn, socket="cloude_pytest_closed", name=f"cloude_{name}",
                epoch=epoch, origin=SESSION_ORIGIN_OBSERVED,
                lifecycle=SESSION_LIFECYCLE_STOPPED, lifecycle_source=source, now=stamp,
            )
        record_instance(
            conn, socket="cloude_pytest_closed", name="cloude_imported", epoch=3004,
            origin=SESSION_ORIGIN_OBSERVED, lifecycle=SESSION_LIFECYCLE_STOPPED,
            lifecycle_source="import", now="2026-09-30T20:00:00Z",
        )
        conn.execute(
            "UPDATE sessions SET last_work_at = ? WHERE tmux_name = ?",
            ("2026-09-30T09:00:00Z", "cloude_imported"),
        )
        conn.commit()
    finally:
        conn.close()


def _names(monkeypatch, tmp_path):
    monkeypatch.setattr(type(_routes_settings()), "get_state_dir", lambda self: tmp_path)
    _seed(tmp_path)
    client = _recent_client(_HealthManager(ProbeHealth(ok=True)))
    return client.get("/api/v1/sessions/recent").json()["sessions"]


def test_recent_is_ordered_by_close_time_newest_first_with_a_labelled_basis(monkeypatch, tmp_path):
    rows = _names(monkeypatch, tmp_path)
    assert [r["tmux_name"] for r in rows] == [
        "cloude_last", "cloude_mid", "cloude_imported", "cloude_first",
    ]
    by_name = {r["tmux_name"]: r for r in rows}
    assert by_name["cloude_last"]["closed_at"] == "2026-09-30T12:00:00Z"
    assert by_name["cloude_last"]["closed_basis"] == "closed"
    assert by_name["cloude_imported"]["closed_at"] == "2026-09-30T09:00:00Z"
    assert by_name["cloude_imported"]["closed_basis"] == "last_active"


def test_the_sort_direction_is_one_flippable_constant(monkeypatch, tmp_path):
    monkeypatch.setattr(session_closed_time, "RECENT_NEWEST_CLOSED_FIRST", False)
    rows = _names(monkeypatch, tmp_path)
    assert [r["tmux_name"] for r in rows] == [
        "cloude_first", "cloude_imported", "cloude_mid", "cloude_last",
    ]
