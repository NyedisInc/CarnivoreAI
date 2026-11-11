
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.core import plugin_layout
from src.core.db import connect, db_path_for
from src.cplugs.host import registry_boot, registry_files, registry_migration, registry_store
from src.cplugs.host import state as owner_state
from tests.python.cplugs import registry_world as W
from tests.python.cplugs.test_registry_migration_full_tuple import Alerts, boot


def _backups(state: Path) -> list:
    return sorted(registry_files.cplugs_dir(state).glob("migration-backup-*"))


def test_a_retired_step_that_writes_does_not_undo_the_flip(tmp_path):
    w = W.support(tmp_path)
    outcome = registry_boot.run(w.state, retired=lambda: owner_state.forget(w.state, "xtalk"), alert=Alerts())
    assert outcome.action == registry_boot.A_MIGRATED
    doc, status = registry_files.load_registry(w.state)
    assert status == registry_files.STATUS_OK and registry_files.is_migrated(doc)
    assert registry_files.LEDGER_COPY_KEY in doc or registry_files.MIGRATION_KEY in doc
    backups = len(_backups(w.state))
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL and len(_backups(w.state)) == backups


def test_a_busy_lock_is_a_read_only_boot_with_an_alert(tmp_path, monkeypatch):
    w = W.support(tmp_path)

    def busy(*args, **kwargs):
        raise registry_store.RegistryBusy("held elsewhere")

    monkeypatch.setattr(registry_store, "exclusive", busy)
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    monkeypatch.undo()
    assert outcome.action == registry_boot.A_READ_ONLY and outcome.read_only
    assert [a["key"] for a in alerts.rows] == [registry_boot.KEY_READ_ONLY] and alerts.rows[0]["params"] == {"reason": "registry_busy"}
    registry_files.clear_read_only(w.state)


@pytest.mark.parametrize("breaker", ["plan", "apply", "scratch"])
def test_an_os_error_in_the_commit_steps_is_a_refusal_not_a_crash(tmp_path, monkeypatch, breaker):
    w = W.support(tmp_path)

    def full(*args, **kwargs):
        raise PermissionError(28, "no space left on device")

    if breaker == "plan":
        monkeypatch.setattr(plugin_layout, "plan_moves", full)
    elif breaker == "apply":
        monkeypatch.setattr(plugin_layout, "apply_moves", full)
    else:
        monkeypatch.setattr(tempfile, "TemporaryDirectory", full)
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    monkeypatch.undo()
    assert outcome.action == registry_boot.A_REFUSED
    assert [a["key"] for a in alerts.rows] == [registry_boot.KEY_REFUSED]
    assert (w.state / "cplug-code").is_dir() and not (w.state / "plugins").exists()
    assert registry_files.is_migrated(registry_files.load_registry(w.state)[0]) is False


def test_a_marker_left_at_zero_by_a_crash_is_healed_at_the_next_boot(tmp_path):
    w = W.support(tmp_path)
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    generation = registry_files.read_generation(w.state)
    conn = connect(db_path_for(w.state), create=False)
    try:
        conn.execute("UPDATE plugin_registry_marker SET generation = ?, migration_version = 0 WHERE id = 1", (generation - 1,))
        conn.commit()
    finally:
        conn.close()
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL
    held = registry_files.read_marker(w.state)
    assert held.migration_version == registry_files.MIGRATION_VERSION and held.generation == generation
    registry_files.registry_path(w.state).unlink()
    registry_files.registry_path(w.state).with_suffix(".json.bak").unlink(missing_ok=True)
    assert boot(w.state, Alerts()).action != registry_boot.A_MIGRATED
    registry_files.clear_read_only(w.state)


def test_the_bak_copy_is_written_by_temp_and_replace(tmp_path, monkeypatch):
    w = W.support(tmp_path)
    boot(w.state, Alerts())
    target = registry_files.registry_path(w.state)
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda src, dst: (seen.append(Path(dst).name), real(src, dst))[1])
    registry_files.write_registry(target, registry_files.load_registry(w.state)[0])
    assert target.name + ".bak" in seen and target.name in seen


def test_a_refusal_that_repeats_every_boot_keeps_one_backup(tmp_path, monkeypatch):
    w = W.support(tmp_path)

    def refuse(*args, **kwargs):
        raise registry_migration.MigrationRefused("compare_failed", "forced", item="x", field_name="y")

    monkeypatch.setattr(registry_migration, "compare", refuse)
    for _ in range(3):
        assert boot(w.state, Alerts()).action == registry_boot.A_REFUSED
    monkeypatch.undo()
    assert len(_backups(w.state)) == 1
