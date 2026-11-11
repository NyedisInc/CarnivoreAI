
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from src.core.db import connect, db_path_for
from src.cplugs.host import registry_boot, registry_files, registry_migration, registry_store
from src.cplugs.host import state as owner_state
from tests.python.cplugs import registry_world as W
from tests.python.cplugs.test_registry_migration_full_tuple import Alerts, boot

CATALOG = Path(__file__).resolve().parents[3] / "client" / "js" / "i18n" / "catalog.en.js"
STICKY = {registry_boot.KEY_REFUSED, registry_boot.KEY_READ_ONLY, registry_boot.KEY_RESTORED, registry_boot.KEY_OLDER}


@pytest.fixture
def resolved(monkeypatch) -> List[str]:
    keys: List[str] = []
    monkeypatch.setattr(registry_boot.alert_service, "resolve", lambda key, **kw: keys.append(key) or [])
    return keys


def test_a_busy_lock_alert_says_the_lock_was_busy_not_that_the_file_could_not_be_trusted(tmp_path, monkeypatch):
    w = W.support(tmp_path)
    monkeypatch.setattr(registry_store, "exclusive", lambda *a, **k: (_ for _ in ()).throw(registry_store.RegistryBusy("held elsewhere")))
    alerts = Alerts()
    boot(w.state, alerts)
    monkeypatch.undo()
    registry_files.clear_read_only(w.state)
    assert alerts.rows[0]["detail_key"] == "app_alert.plugin_registry.busy.detail"
    catalog = CATALOG.read_text(encoding="utf-8")
    assert "'app_alert.plugin_registry.busy.detail':" in catalog and "'app_alert.plugin_registry.read_only.title':" in catalog


def test_a_read_only_alert_for_an_unreadable_file_keeps_its_own_words(tmp_path):
    w = W.support(tmp_path)
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    registry_files.registry_path(w.state).write_text("{", encoding="utf-8")
    registry_files.registry_path(w.state).with_suffix(".json.bak").write_text("{", encoding="utf-8")
    for folder in registry_files.cplugs_dir(w.state).glob("migration-backup-*"):
        for f in folder.glob("*.json"):
            f.write_text("{", encoding="utf-8")
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    registry_files.clear_read_only(w.state)
    assert outcome.action == registry_boot.A_READ_ONLY and alerts.rows[0]["detail_key"] == "app_alert.plugin_registry.read_only.detail"


def test_the_sticky_alerts_are_resolved_on_a_migrated_boot_and_on_a_normal_boot(tmp_path, resolved):
    w = W.support(tmp_path)
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    assert STICKY <= set(resolved)
    resolved.clear()
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL
    assert STICKY <= set(resolved)


def test_a_boot_that_stays_refused_or_read_only_resolves_nothing(tmp_path, monkeypatch, resolved):
    w = W.support(tmp_path)
    monkeypatch.setattr(registry_migration, "compare", lambda *a, **k: (_ for _ in ()).throw(registry_migration.MigrationRefused("compare_failed", "x")))
    assert boot(w.state, Alerts()).action == registry_boot.A_REFUSED
    assert resolved == []


def test_a_missing_marker_row_is_healed_when_the_file_is_flipped(tmp_path):
    w = W.support(tmp_path)
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    conn = connect(db_path_for(w.state), create=False)
    try:
        conn.execute("DELETE FROM plugin_registry_marker")
        conn.commit()
    finally:
        conn.close()
    assert registry_files.read_marker(w.state) is None
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL
    held = registry_files.read_marker(w.state)
    assert held is not None and held.generation == registry_files.read_generation(w.state) and held.migration_version >= registry_files.MIGRATION_VERSION


def test_a_refusal_that_repeats_keeps_one_backup_even_when_the_retired_step_writes(tmp_path, monkeypatch):
    w = W.support(tmp_path)
    monkeypatch.setattr(registry_migration, "compare", lambda *a, **k: (_ for _ in ()).throw(registry_migration.MigrationRefused("compare_failed", "x")))
    for _ in range(3):
        outcome = registry_boot.run(w.state, retired=lambda: owner_state.forget(w.state, "xtalk"), alert=Alerts())
        assert outcome.action == registry_boot.A_REFUSED
    monkeypatch.undo()
    assert len(sorted(registry_files.cplugs_dir(w.state).glob("migration-backup-*"))) == 1


def test_a_real_change_to_the_old_files_between_refusals_still_gets_a_new_backup(tmp_path, monkeypatch):
    w = W.support(tmp_path)
    monkeypatch.setattr(registry_migration, "compare", lambda *a, **k: (_ for _ in ()).throw(registry_migration.MigrationRefused("compare_failed", "x")))
    assert boot(w.state, Alerts()).action == registry_boot.A_REFUSED
    owner_state.forget(w.state, "huddle")
    assert boot(w.state, Alerts()).action == registry_boot.A_REFUSED
    monkeypatch.undo()
    assert len(sorted(registry_files.cplugs_dir(w.state).glob("migration-backup-*"))) == 2


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
    assert registry_store.write_document(state, "state", {"cplugs": {}}, log_event="t") is False
