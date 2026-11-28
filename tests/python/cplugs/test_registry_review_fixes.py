
from __future__ import annotations

import os
from pathlib import Path

from src.core.db import connect, db_path_for
from src.plugins.host import registry_boot, registry_store, runtime
from src.plugins.host import state as owner_state
from tests.python.cplugs.test_registry_boot_tiebreaks import Alerts, boot, migrated, support


def test_a_retired_step_that_writes_on_fresh_boot_produces_valid_v3_registry(tmp_path):
    state = support(tmp_path)
    manifest = runtime.find("taskmanager").manifest
    outcome = registry_boot.run(
        state,
        retired=lambda: owner_state.update(state, manifest, None, lambda st: st),
        alert=Alerts(),
    )
    assert outcome.action == registry_boot.A_NORMAL
    doc, status = registry_store.load_registry(state)
    assert status == registry_store.STATUS_OK and registry_store.is_migrated(doc)
    held = registry_store.read_marker(state)
    assert held is not None and held.generation == doc["generation"] and held.migration_version >= registry_store.MIGRATION_VERSION
    assert boot(state, Alerts()).action == registry_boot.A_NORMAL


def test_a_busy_lock_is_a_read_only_boot_with_an_alert(tmp_path, monkeypatch):
    w = migrated(tmp_path)

    def busy(*args, **kwargs):
        raise registry_store.RegistryBusy("held elsewhere")

    monkeypatch.setattr(registry_store, "exclusive", busy)
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    monkeypatch.undo()
    assert outcome.action == registry_boot.A_READ_ONLY and outcome.read_only
    assert [a["key"] for a in alerts.rows] == [registry_boot.KEY_READ_ONLY]
    assert alerts.rows[0]["params"] == {"reason": "registry_busy"}
    registry_store.clear_read_only(w.state)


def test_a_marker_left_at_zero_by_a_crash_is_healed_at_the_next_boot(tmp_path):
    w = migrated(tmp_path)
    generation = registry_store.read_generation(w.state)
    conn = connect(db_path_for(w.state), create=False)
    try:
        conn.execute("UPDATE plugin_registry_marker SET generation = ?, migration_version = 0 WHERE id = 1", (generation - 1,))
        conn.commit()
    finally:
        conn.close()
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL
    held = registry_store.read_marker(w.state)
    assert held.migration_version == registry_store.MIGRATION_VERSION and held.generation == generation
    registry_store.registry_path(w.state).unlink()
    registry_store.registry_path(w.state).with_suffix(".json.bak").unlink(missing_ok=True)
    assert boot(w.state, Alerts()).action == registry_boot.A_READ_ONLY
    registry_store.clear_read_only(w.state)


def test_the_bak_copy_is_written_by_temp_and_replace(tmp_path, monkeypatch):
    w = migrated(tmp_path)
    target = registry_store.registry_path(w.state)
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda src, dst: (seen.append(Path(dst).name), real(src, dst))[1])
    registry_store.write_registry(target, registry_store.load_registry(w.state)[0])
    assert target.name + ".bak" in seen and target.name in seen
