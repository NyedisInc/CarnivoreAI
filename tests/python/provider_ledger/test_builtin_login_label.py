
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.core import ui_preferences
from src.core.provider_ledger import poller_scan
from src.core.provider_ledger.poller_core import LedgerPoller
from src.core.provider_ledger.poller_state import AccountState

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def test_default_name_is_unchanged_without_a_label():
    assert poller_scan.default_login_row().name == "this device's claude login"


def test_default_name_has_a_short_form_for_narrow_spots():
    assert poller_scan.default_login_row().short_name == "this device"


def test_a_label_drops_the_default_short_form():
    assert poller_scan.default_login_row("work laptop").short_name is None


def test_label_renames_only_the_display_name():
    row = poller_scan.default_login_row("work laptop")
    assert row.name == "work laptop"
    assert row.id == poller_scan.AUTO_DEFAULT_ACCOUNT_ID
    assert row.claude_config_dir == poller_scan.default_login_row().claude_config_dir


def test_a_rename_does_not_schedule_a_usage_read():
    old = poller_scan.default_login_row()
    later = datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)
    state = AccountState(account=old, next_poll_at=later)
    poller_scan.reconcile({old.id: state}, set(), [poller_scan.default_login_row("x")], NOW)
    assert state.account.name == "x"
    assert state.next_poll_at == later


def test_a_pointer_change_still_schedules_a_read():
    old = poller_scan.default_login_row()
    later = datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)
    state = AccountState(account=old, next_poll_at=later)
    moved = old.model_copy(update={"claude_config_dir": "~/elsewhere"})
    poller_scan.reconcile({old.id: state}, set(), [moved], NOW)
    assert state.next_poll_at == NOW


@pytest.mark.parametrize("bad", ["", "   ", "x" * 41, "a\nb"])
def test_the_preference_refuses_bad_labels(bad):
    with pytest.raises(ValueError):
        ui_preferences.validate_changes({"builtin_login_label": bad})


def test_the_preference_trims_and_null_resets():
    assert ui_preferences.validate_changes({"builtin_login_label": "  home  "}) == {
        "builtin_login_label": "home"
    }
    assert ui_preferences.validate_changes({"builtin_login_label": None}) == {
        "builtin_login_label": None
    }


def test_the_poller_reads_the_label_from_the_preferences_projection():
    store = SimpleNamespace(read=lambda: {"values": {"builtin_login_label": "home"}})
    poller = LedgerPoller(app_state=SimpleNamespace(ui_preferences_store=store))
    assert poller._builtin_login_label() == "home"
    assert LedgerPoller(app_state=None)._builtin_login_label() is None
