
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from src.core.db import connect, db_path_for
from src.plugins.host import registry_boot, registry_store
from src.plugins.host import state as owner_state
from tests.python.cplugs.test_registry_boot_tiebreaks import Alerts, boot, migrated

CATALOG = Path(__file__).resolve().parents[3] / "client" / "js" / "i18n" / "catalog.en.js"
STICKY = {registry_boot.KEY_REFUSED, registry_boot.KEY_READ_ONLY, registry_boot.KEY_RESTORED, registry_boot.KEY_OLDER}


@pytest.fixture
def resolved(monkeypatch) -> List[str]:
    keys: List[str] = []
    monkeypatch.setattr(registry_boot.alert_service, "resolve", lambda key, **kw: keys.append(key) or [])
    return keys


def test_a_busy_lock_alert_says_the_lock_was_busy_not_that_the_file_could_not_be_trusted(tmp_path, monkeypatch):
    w = migrated(tmp_path)
    monkeypatch.setattr(registry_store, "exclusive", lambda *a, **k: (_ for _ in ()).throw(registry_store.RegistryBusy("held elsewhere")))
    alerts = Alerts()
    boot(w.state, alerts)
    monkeypatch.undo()
    registry_store.clear_read_only(w.state)
    assert alerts.rows[0]["detail_key"] == "app_alert.plugin_registry.busy.detail"
    catalog = CATALOG.read_text(encoding="utf-8")
    assert "'app_alert.plugin_registry.busy.detail':" in catalog and "'app_alert.plugin_registry.read_only.title':" in catalog


def test_a_read_only_alert_for_an_unreadable_file_keeps_its_own_words(tmp_path):
    w = migrated(tmp_path)
    registry_store.registry_path(w.state).write_text("{", encoding="utf-8")
    registry_store.registry_path(w.state).with_suffix(".json.bak").write_text("{", encoding="utf-8")
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    registry_store.clear_read_only(w.state)
    assert outcome.action == registry_boot.A_READ_ONLY and alerts.rows[0]["detail_key"] == "app_alert.plugin_registry.read_only.detail"


def test_the_sticky_alerts_are_resolved_on_a_normal_boot(tmp_path, resolved):
    w = migrated(tmp_path)
    resolved.clear()
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL
    assert STICKY <= set(resolved)


def test_a_boot_that_stays_read_only_resolves_nothing(tmp_path, resolved):
    w = migrated(tmp_path)
    registry_store.registry_path(w.state).write_text("{", encoding="utf-8")
    registry_store.registry_path(w.state).with_suffix(".json.bak").write_text("{", encoding="utf-8")
    resolved.clear()
    assert boot(w.state, Alerts()).action == registry_boot.A_READ_ONLY
    registry_store.clear_read_only(w.state)
    assert resolved == []


def test_a_missing_marker_row_is_healed_when_the_file_is_flipped(tmp_path):
    w = migrated(tmp_path)
    conn = connect(db_path_for(w.state), create=False)
    try:
        conn.execute("DELETE FROM plugin_registry_marker")
        conn.commit()
    finally:
        conn.close()
    assert registry_store.read_marker(w.state) is None
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL
    held = registry_store.read_marker(w.state)
    assert held is not None and held.generation == registry_store.read_generation(w.state)
    assert held.migration_version >= registry_store.MIGRATION_VERSION


def test_a_state_folder_whose_parent_is_a_file_is_a_busy_refusal_not_a_raw_oserror(tmp_path):
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    state = blocker / "state"
    with pytest.raises(registry_store.RegistryBusy):
        with registry_store.exclusive(state):
            pass
    with pytest.raises(owner_state.StateWriteFailed):
        with registry_store.exclusive(state, busy_error=owner_state.StateWriteFailed):
            pass
    assert registry_store.save_document(state, registry_store.new_document(), log_event="t") is False
