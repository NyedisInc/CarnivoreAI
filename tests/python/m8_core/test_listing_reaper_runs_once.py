from __future__ import annotations

from src.core.tmux_listing import TmuxListing
from tests.test_session_lifecycle_wiring import _wired
from src.core.db_migration import ensure_db_migrated


def test_one_reconcile_per_listing(monkeypatch, tmp_path) -> None:
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    mgr = _wired(monkeypatch, tmp_path,
                 TmuxListing.answered([{"name": "cloude_a", "created_at_epoch": 1000, "window_count": 1}]))
    calls: list = []
    real = mgr.reconcile_lifecycle

    def spy(listing, pane_status=None):
        calls.append(pane_status)
        return real(listing, pane_status)

    monkeypatch.setattr(mgr, "reconcile_lifecycle", spy)
    assert mgr.list_attachable_sessions().ok is True
    assert len(calls) == 1
