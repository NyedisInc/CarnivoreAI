
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

from src.core.db import connect, db_path_for
from src.cplugs.host import registry_boot, registry_files, registry_projection, registry_store
from src.cplugs.host import state as owner_state
from tests.python.cplugs import registry_world as W
from tests.python.cplugs.test_registry_migration_full_tuple import Alerts, boot


def migrated(tmp_path: Path) -> Any:
    w = W.support(tmp_path)
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    return w


def set_marker(state: Path, generation: int) -> None:
    conn = connect(db_path_for(state), create=False)
    try:
        conn.execute("UPDATE plugin_registry_marker SET generation = ? WHERE id = 1", (generation,))
        conn.commit()
    finally:
        conn.close()


def test_equal_generations_boot_normally_and_run_the_per_boot_steps(tmp_path):
    w = migrated(tmp_path)
    calls, alerts = [], Alerts()
    outcome = boot(w.state, alerts, calls)
    assert (outcome.action, outcome.read_only, calls, alerts.rows) == (registry_boot.A_NORMAL, False, ["retired"], [])


def test_a_file_lower_than_the_marker_is_a_read_only_boot_with_one_alert(tmp_path):
    w = migrated(tmp_path)
    gen = registry_files.read_generation(w.state)
    set_marker(w.state, gen + 5)
    alerts, calls = Alerts(), []
    outcome = boot(w.state, alerts, calls)
    assert outcome.action == registry_boot.A_OLDER_COPY and outcome.read_only and calls == []
    assert [a["key"] for a in alerts.rows] == [registry_boot.KEY_OLDER]
    assert alerts.rows[0]["params"] == {"file": gen, "database": gen + 5}
    assert {a["id"] for a in alerts.rows[0]["actions"]} == {"keep", "backup"} and alerts.rows[0]["actions"][0]["route"] == registry_boot.RESOLVE_ROUTE
    before = W.files_bytes(w.state)
    try:
        owner_state.forget(w.state, "xtalk")
        raise AssertionError("a write was accepted in a read-only boot")
    except owner_state.StateWriteFailed:
        pass
    assert W.files_bytes(w.state) == before
    assert owner_state.stored_entry(w.state, "huddle") == W.JOE_STATE["huddle"]
    registry_files.clear_read_only(w.state)


def test_keeping_the_older_file_lifts_read_only_and_goes_above_the_marker(tmp_path):
    w = migrated(tmp_path)
    gen = registry_files.read_generation(w.state)
    set_marker(w.state, gen + 5)
    boot(w.state, Alerts())
    assert registry_boot.resolve(w.state, registry_boot.CHOICE_KEEP) is True
    assert registry_files.read_only_reason(w.state) is None
    assert registry_files.read_generation(w.state) == gen + 6 == registry_files.read_marker(w.state).generation
    assert owner_state.forget(w.state, "xtalk") is True
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL


def test_using_the_backup_restores_the_bak_copy_and_lifts_read_only(tmp_path):
    w = migrated(tmp_path)
    owner_state.forget(w.state, "xtalk")
    gen = registry_files.read_generation(w.state)
    set_marker(w.state, gen + 3)
    boot(w.state, Alerts())
    assert registry_boot.resolve(w.state, registry_boot.CHOICE_BACKUP) is True
    assert registry_files.read_only_reason(w.state) is None
    assert "xtalk" in registry_files.load_registry(w.state)[0]["items"]
    assert registry_files.read_generation(w.state) > gen + 3


def test_a_file_higher_than_the_marker_is_accepted_and_the_marker_follows(tmp_path):
    w = migrated(tmp_path)
    gen = registry_files.read_generation(w.state)
    set_marker(w.state, gen - 1)
    alerts = Alerts()
    assert boot(w.state, alerts).action == registry_boot.A_NORMAL and alerts.rows == []
    assert registry_files.read_marker(w.state).generation == gen and registry_files.read_generation(w.state) == gen


def test_a_newer_state_json_from_a_rollback_build_is_read_back_for_the_fields_it_knows(tmp_path):
    w = migrated(tmp_path)
    path = registry_files.legacy_path(w.state, "state")
    doc = json.loads(path.read_text())
    doc.pop(registry_projection.MIRROR_STAMP)
    doc["cplugs"]["huddle"].update(enabled=False, revision=13, settings={**doc["cplugs"]["huddle"]["settings"], "view": "board"})
    doc["cplugs"]["brandnew"] = {"enabled": True, "grants": [], "settings": {}, "revision": 1, "digest": None, "updated_at": 9.0}
    path.write_text(json.dumps(doc))
    future = time.time() + 10
    os.utime(path, (future, future))
    before_item = registry_files.load_registry(w.state)[0]["items"]["clock"]
    outcome = boot(w.state, Alerts())
    assert outcome.action == registry_boot.A_REIMPORTED and outcome.reimported == ["brandnew", "huddle"]
    fresh = registry_files.load_registry(w.state)[0]
    assert fresh["items"]["huddle"]["enabled"] is False and fresh["items"]["huddle"]["settings"]["view"] == "board" and fresh["items"]["huddle"]["revision"] == 13
    assert fresh["items"]["brandnew"]["enabled"] is True
    assert fresh["items"]["clock"] == before_item
    assert fresh["items"]["clock"]["install_uuid"] == W.UUID_CLOCK
    assert json.loads(path.read_text())[registry_projection.MIRROR_STAMP] == fresh["generation"]


def test_a_stamped_or_older_mirror_is_not_read_back(tmp_path):
    w = migrated(tmp_path)
    path = registry_files.legacy_path(w.state, "state")
    doc = json.loads(path.read_text())
    doc["cplugs"]["huddle"]["enabled"] = False
    path.write_text(json.dumps(doc))
    future = time.time() + 10
    os.utime(path, (future, future))
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL
    assert owner_state.stored_entry(w.state, "huddle")["enabled"] is True


def test_an_unreadable_plugins_json_falls_back_to_the_bak_copy(tmp_path):
    w = migrated(tmp_path)
    owner_state.forget(w.state, "xtalk")
    registry_files.registry_path(w.state).write_text("{ torn")
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    assert outcome.action == registry_boot.A_RESTORED and outcome.detail == "plugins.json.bak"
    assert registry_files.is_migrated(registry_files.load_registry(w.state)[0]) and [a["key"] for a in alerts.rows] == [registry_boot.KEY_RESTORED]
    assert registry_files.read_generation(w.state) == registry_files.read_marker(w.state).generation


def test_with_no_bak_the_newest_migration_backup_is_used(tmp_path):
    w = migrated(tmp_path)
    registry_files.registry_path(w.state).write_text("{ torn")
    registry_files.registry_path(w.state).with_suffix(".json.bak").unlink(missing_ok=True)
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    assert outcome.action == registry_boot.A_RESTORED and outcome.detail.startswith("migration-backup-")
    assert owner_state.stored_entry(w.state, "huddle") == W.JOE_STATE["huddle"]
    assert registry_files.is_migrated(registry_files.load_registry(w.state)[0])


def test_a_missing_plugins_json_with_a_marker_is_never_a_first_boot(tmp_path):
    w = migrated(tmp_path)
    registry_files.registry_path(w.state).unlink()
    registry_files.registry_path(w.state).with_suffix(".json.bak").unlink(missing_ok=True)
    outcome = boot(w.state, Alerts())
    assert outcome.action == registry_boot.A_RESTORED
    assert len(list(registry_files.cplugs_dir(w.state).glob("migration-backup-*"))) == 1


def test_when_nothing_reads_the_boot_is_read_only_and_every_plugin_keeps_its_mirrored_state(tmp_path):
    w = migrated(tmp_path)
    registry_files.registry_path(w.state).write_text("{ torn")
    registry_files.registry_path(w.state).with_suffix(".json.bak").write_text("{ torn")
    for folder in registry_files.cplugs_dir(w.state).glob("migration-backup-*"):
        (folder / "state.json").write_text("{ torn")
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    assert outcome.action == registry_boot.A_READ_ONLY and outcome.read_only
    assert [(a["key"], a["severity"]) for a in alerts.rows] == [(registry_boot.KEY_READ_ONLY, "error")]
    before = W.files_bytes(w.state)
    assert owner_state.stored_entry(w.state, "huddle") == W.JOE_STATE["huddle"]
    assert registry_store.write_document(w.state, "third_party", {"enabled": False}, log_event="t") is False
    assert W.files_bytes(w.state) == before and registry_store.describe(w.state)[1] == registry_store.SOURCE_READ_ONLY
    registry_files.clear_read_only(w.state)


def test_a_lock_held_by_another_process_is_a_read_only_boot(tmp_path, monkeypatch):
    w = migrated(tmp_path)
    monkeypatch.setattr(registry_store, "LOCK_WAIT_SECONDS", 0.05)
    held: Dict[str, Any] = {}

    def busy(path, timeout):
        raise registry_store.RegistryBusy("another process holds the plugin registry lock")

    monkeypatch.setattr(registry_store, "_take_flock", busy)
    outcome = boot(w.state, Alerts())
    held["x"] = outcome
    monkeypatch.undo()
    assert outcome.action == registry_boot.A_READ_ONLY and outcome.detail == "registry_busy"
    registry_files.clear_read_only(w.state)
