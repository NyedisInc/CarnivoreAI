
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.plugins.host import identity, owner_switch, registry_boot, registry_files, registry_migration, registry_projection, registry_store, risk, sideload
from src.plugins.host import state as owner_state
from src.plugins.runtime.integrity import tree_digest
from tests.python.cplugs import registry_world as W


class Alerts:

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def __call__(self, key: str, **kwargs: Any) -> None:
        self.rows.append({"key": key, **kwargs})


def boot(state: Path, alerts: Alerts, calls: Optional[List[str]] = None) -> registry_boot.BootOutcome:
    return registry_boot.run(state, retired=lambda: calls.append("retired") if calls is not None else None, alert=alerts)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("shape", ["joe", "second"])
def test_every_item_reads_the_same_tuple_after_the_migration(tmp_path, shape):
    w = W.support(tmp_path, shape)
    before_state = json.loads(json.dumps(w.docs["state"]["cplugs"]))
    alerts, calls = Alerts(), []
    assert boot(w.state, alerts, calls).action == registry_boot.A_MIGRATED
    assert alerts.rows == [] and calls == ["retired"]
    assert registry_files.is_migrated(registry_files.load_registry(w.state)[0])
    assert owner_state.stored_ids(w.state) == tuple(sorted(before_state))
    for item, entry in before_state.items():
        assert owner_state.stored_entry(w.state, item) == entry
        assert set(entry) >= set(registry_projection.STATE_DEFAULTS)
    assert owner_switch.read(w.state) is w.docs["third_party"]["enabled"]
    if shape == "joe":
        assert owner_state.stored_entry(w.state, "reviewboard")["settings"]["trustedProxies"] == ["192.0.2.11"]
        assert owner_state.stored_entry(w.state, "huddle")["settings"] == W.JOE_STATE["huddle"]["settings"]
        names = {r.name: (r.uuid, r.catalog_id, r.publisher_key_id, r.source) for r in identity.installs(w.state)}
        assert names["clock"] == (W.UUID_CLOCK, "acme/clock", "KEYOK", "") and names["myclock"][3] == str(w.source)
        assert identity.removal_of(w.state, "oldtool") == {"at": "2026-11-09T00:00:00Z", "version": "0.9.1", "publisher_key_id": "KEYOK"}
        assert sideload.items(w.state) == w.docs["sideload"]["items"] and sideload.duration_hours(w.state) == 24
        assert sideload.expires_at(w.state) == 1762732800.0


def test_the_joined_documents_equal_the_old_files_and_the_mirror_carries_the_generation(tmp_path):
    w = W.support(tmp_path)
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    doc = registry_files.load_registry(w.state)[0]
    assert registry_projection.join(doc) == registry_projection.normalize(w.docs)
    for name, file_name in registry_files.LEGACY_FILES.items():
        mirrored = json.loads((registry_files.cplugs_dir(w.state) / file_name).read_text())
        assert mirrored[registry_projection.MIRROR_STAMP] == doc["generation"]
        assert {k: v for k, v in mirrored.items() if k != registry_projection.MIRROR_STAMP} == registry_projection.join(doc)[name]
    held = registry_files.read_marker(w.state)
    assert (held.generation, held.migration_version) == (doc["generation"], 1) and held.migrated_at == doc["migration"]["migrated_at"]


def test_the_backup_is_verified_and_holds_every_source_and_the_ledger_rows(tmp_path):
    w = W.support(tmp_path)
    originals = {n: sha(registry_files.legacy_path(w.state, n)) for n in registry_files.LEGACY_FILES}
    outcome = registry_migration.migrate(w.state, retired=lambda: None)
    assert outcome.outcome == registry_migration.OUTCOME_MIGRATED
    backup = outcome.backup
    assert backup.name == f"migration-backup-{outcome.generation}" and backup.parent == registry_files.cplugs_dir(w.state)
    for name, file_name in registry_files.LEGACY_FILES.items():
        assert sha(backup / file_name) == originals[name]
    rows = json.loads((backup / registry_migration.LEDGER_DUMP_NAME).read_text())
    assert sorted(r["item_id"] for r in rows) == ["acme/clock", "local/myclock"]
    assert json.loads((backup / registry_migration.JOURNAL_NAME).read_text())["moves"]


def test_the_ledger_facts_are_copied_not_recomputed(tmp_path):
    w = W.support(tmp_path)
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    copy = registry_files.load_registry(w.state)[0][registry_files.LEDGER_COPY_KEY]
    assert copy["clock"] == {"version": "1.2.0", "digest": "d1", "consented_digest": "d1", "consented_body_sha": None, "publisher_key_id": "KEYOK",
                             "auto_update": False, "revision": 3, "installed_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-02T00:00:00Z", "consent_via": "sheet"}
    assert set(copy) == {"clock", "myclock"}
    owner_state.forget(w.state, "xtalk")
    assert registry_files.load_registry(w.state)[0][registry_files.LEDGER_COPY_KEY] == copy


def test_an_empty_tree_migrates_to_an_empty_registry(tmp_path):
    w = W.support(tmp_path, "empty")
    alerts = Alerts()
    assert boot(w.state, alerts).action == registry_boot.A_MIGRATED
    doc = registry_files.load_registry(w.state)[0]
    assert doc["items"] == {} and doc["tombstones"] == {} and doc["switches"] == {"third_party": False} and alerts.rows == []
    assert owner_state.stored_ids(w.state) == () and identity.installs(w.state) == [] and owner_switch.read(w.state) is False


def test_a_tampered_plugin_folder_still_reads_needs_approval_because_the_migration_never_hashes(tmp_path):
    w = W.support(tmp_path)
    (w.code["clock"] / "main.py").write_text("print('tampered')\n")
    assert boot(w.state, Alerts()).action == registry_boot.A_MIGRATED
    stored = owner_state.stored_entry(w.state, "clock")
    assert stored["digest"] == "sha256:old-approval"
    assert risk.consent_owed("local", tree_digest(w.state / "plugins" / "clock"), stored["digest"]) is True


def test_an_unreadable_state_json_migrates_nothing_and_raises_one_alert(tmp_path):
    w = W.support(tmp_path)
    registry_files.legacy_path(w.state, "state").write_text("{ this is not json")
    before = W.files_bytes(w.state)
    alerts, calls = Alerts(), []
    outcome = boot(w.state, alerts, calls)
    assert outcome.action == registry_boot.A_REFUSED and "unreadable_store" in outcome.detail
    assert W.files_bytes(w.state) == before
    assert (w.state / "cplug-code" / "clock").is_dir() and (w.state / "cplugs" / W.UUID_CLOCK).is_dir() and not (w.state / "plugins").exists()
    assert [a["key"] for a in alerts.rows] == [registry_boot.KEY_REFUSED] and alerts.rows[0]["params"]["code"] == "unreadable_store"
    assert calls == ["retired"]
    assert registry_files.is_migrated(registry_files.load_registry(w.state)[0]) is False


def test_a_difference_between_the_readers_writes_nothing_and_names_the_item_and_field(tmp_path, monkeypatch):
    w = W.support(tmp_path)
    real_join = registry_projection.join

    def lossy(registry):
        docs = real_join(registry)
        docs["state"]["cplugs"]["huddle"]["grants"] = []
        return docs

    monkeypatch.setattr(registry_projection, "join", lossy)
    before = W.files_bytes(w.state)
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    monkeypatch.undo()
    assert outcome.action == registry_boot.A_REFUSED
    after = W.files_bytes(w.state)
    assert {k: v for k, v in after.items() if "migration-backup" not in k} == before
    assert (w.state / "cplug-code").is_dir() and not (w.state / "plugins").exists() and not (w.state / "plugin-data").exists()
    assert len(alerts.rows) == 1 and alerts.rows[0]["params"] == {"item": "state", "field": "cplugs", "code": "compare_failed"}
    held = registry_files.read_marker(w.state)
    assert held is None or held.migration_version == 0


def test_a_reader_that_answers_differently_from_the_new_file_refuses_and_names_the_field(tmp_path, monkeypatch):
    w = W.support(tmp_path)
    real = registry_files.flipped_views

    def wrong_switch(state_dir):
        views = real(state_dir)
        return None if views is None else {**views, "third_party": {**views["third_party"], "enabled": not views["third_party"]["enabled"]}}

    monkeypatch.setattr(registry_files, "flipped_views", wrong_switch)
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    monkeypatch.undo()
    assert outcome.action == registry_boot.A_REFUSED
    assert len(alerts.rows) == 1 and alerts.rows[0]["params"]["code"] == "compare_failed" and alerts.rows[0]["params"]["field"] == "third_party"
    assert (w.state / "cplug-code").is_dir() and not (w.state / "plugins").exists()
    assert registry_files.is_migrated(registry_files.load_registry(w.state)[0]) is False


def test_the_migration_runs_the_retired_steps_after_the_backup(tmp_path):
    w = W.support(tmp_path)
    seen: List[bool] = []
    registry_migration.migrate(w.state, retired=lambda: seen.append(any(p.name.startswith("migration-backup-") for p in registry_files.cplugs_dir(w.state).iterdir())))
    assert seen == [True]


def test_a_second_boot_does_not_migrate_again(tmp_path):
    w = W.support(tmp_path)
    boot(w.state, Alerts())
    generation = registry_files.read_generation(w.state)
    backups = sorted(p.name for p in registry_files.cplugs_dir(w.state).glob("migration-backup-*"))
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL
    assert registry_files.read_generation(w.state) == generation
    assert sorted(p.name for p in registry_files.cplugs_dir(w.state).glob("migration-backup-*")) == backups


def test_after_the_flip_a_write_edits_plugins_json_first_and_mirrors_the_four_files(tmp_path):
    w = W.support(tmp_path)
    boot(w.state, Alerts())
    gen = registry_files.read_generation(w.state)
    assert owner_state.forget(w.state, "xtalk") is True
    doc = registry_files.load_registry(w.state)[0]
    assert "xtalk" not in doc["items"] and doc["generation"] == gen + 1
    for file_name in registry_files.LEGACY_FILES.values():
        assert json.loads((registry_files.cplugs_dir(w.state) / file_name).read_text())[registry_projection.MIRROR_STAMP] == gen + 1
    assert "xtalk" not in json.loads(registry_files.legacy_path(w.state, "state").read_text())["cplugs"]
    assert registry_files.read_marker(w.state).generation == gen + 1
    owner_switch.write(w.state, False)
    assert registry_files.load_registry(w.state)[0]["switches"] == {"third_party": False}
    assert json.loads(registry_files.legacy_path(w.state, "third_party").read_text())["enabled"] is False


def test_after_the_flip_the_old_files_are_not_read_even_when_they_are_edited_by_hand(tmp_path):
    w = W.support(tmp_path)
    boot(w.state, Alerts())
    path = registry_files.legacy_path(w.state, "state")
    doc = json.loads(path.read_text())
    doc["cplugs"]["huddle"]["enabled"] = False
    path.write_text(json.dumps(doc))
    assert owner_state.stored_entry(w.state, "huddle")["enabled"] is True


def test_a_commit_after_the_flip_reads_from_plugins_json(tmp_path):
    w = W.support(tmp_path)
    boot(w.state, Alerts())
    registry_store.commit(w.state, lambda docs: docs.load("third_party").update(enabled=False))
    assert owner_switch.read(w.state) is False
    assert registry_store.describe(w.state)[1] == registry_store.SOURCE_REGISTRY
