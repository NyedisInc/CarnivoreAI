from __future__ import annotations

from src.core.session_lifecycle import RECONCILE_EVALUATED, ReconcileOutcome, _reconcile_detail


def test_rename_only_pass_is_a_change() -> None:
    assert ReconcileOutcome(RECONCILE_EVALUATED, True, renamed=1).changed is True


def test_revive_only_pass_is_a_change() -> None:
    assert ReconcileOutcome(RECONCILE_EVALUATED, True, revived=2).changed is True


def test_a_quiet_pass_is_not_a_change() -> None:
    assert ReconcileOutcome(RECONCILE_EVALUATED, True).changed is False


def test_detail_names_both_counts() -> None:
    assert _reconcile_detail(2, 1) == "renamed 2 row(s) in place; revived 1 pane_dead row(s) whose pane is alive again"
    assert _reconcile_detail(0, 0) is None
