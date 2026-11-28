
from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.plugins.host import registry_boot, registry_store
from src.plugins.host import state as owner_state

UUID_CLOCK = "0123456789abcdef0123456789abcdef"
UUID_MINE = "fedcba9876543210fedcba9876543210"

JOE_STATE: Dict[str, Any] = {
    "huddle": {
        "enabled": True,
        "grants": ["net.loopback", "files.read"],
        "revision": 12,
        "digest": None,
        "updated_at": 1762646400.0,
        "settings": {"accordion": True, "density": "compact"},
    },
    "xtalk": {
        "enabled": False,
        "grants": [],
        "revision": 1,
        "digest": None,
        "updated_at": 6.0,
        "settings": {"keepCards": 25},
    },
}


class Alerts:

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def __call__(self, key: str, **kwargs: Any) -> None:
        self.rows.append({"key": key, **kwargs})


def boot(state: Path, alerts: Alerts, calls: Optional[List[str]] = None) -> registry_boot.BootOutcome:
    return registry_boot.run(state, retired=lambda: calls.append("retired") if calls is not None else None, alert=alerts)


def support(tmp_path: Path) -> Path:
    state = tmp_path / "support"
    state.mkdir(parents=True, exist_ok=True)
    ensure_db_migrated(state, 4, "0.8.2")
    return state


def seed_v3(state: Path) -> None:
    def put(doc: Dict[str, Any]) -> None:
        doc["switches"]["third_party"] = True
        doc["items"] = {
            "huddle": {"kind": "feature", **copy.deepcopy(JOE_STATE["huddle"])},
            "xtalk": {"kind": "feature", **copy.deepcopy(JOE_STATE["xtalk"])},
            "clock": {
                "kind": "plugin",
                "source": "catalog",
                "catalog_id": "acme/clock",
                "install_uuid": UUID_CLOCK,
                "publisher_key_id": "KEYOK",
                "enabled": True,
                "grants": ["net.fetch"],
                "settings": {"tz": "UTC"},
                "revision": 3,
                "digest": "sha256:old-approval",
                "updated_at": 7.0,
            },
        }

    registry_store.commit(state, put)


def migrated(tmp_path: Path) -> Any:
    state = support(tmp_path)
    seed_v3(state)
    assert boot(state, Alerts()).action == registry_boot.A_NORMAL
    return type("World", (), {"state": state})()


def set_marker(state: Path, generation: int) -> None:
    conn = connect(db_path_for(state), create=False)
    try:
        conn.execute("UPDATE plugin_registry_marker SET generation = ? WHERE id = 1", (generation,))
        conn.commit()
    finally:
        conn.close()


def _files_bytes(state: Path) -> Dict[str, bytes]:
    return {
        p.relative_to(state).as_posix(): p.read_bytes()
        for p in sorted(state.rglob("*"))
        if p.is_file() and not p.name.startswith("carnivore.db") and p.name != ".plugins.lock"
    }


def test_equal_generations_boot_normally_and_run_the_per_boot_steps(tmp_path):
    w = migrated(tmp_path)
    calls, alerts = [], Alerts()
    outcome = boot(w.state, alerts, calls)
    assert (outcome.action, outcome.read_only, calls, alerts.rows) == (registry_boot.A_NORMAL, False, ["retired"], [])


def test_a_file_lower_than_the_marker_is_a_read_only_boot_with_one_alert(tmp_path):
    w = migrated(tmp_path)
    gen = registry_store.read_generation(w.state)
    set_marker(w.state, gen + 5)
    alerts, calls = Alerts(), []
    outcome = boot(w.state, alerts, calls)
    assert outcome.action == registry_boot.A_OLDER_COPY and outcome.read_only and calls == []
    assert [a["key"] for a in alerts.rows] == [registry_boot.KEY_OLDER]
    assert alerts.rows[0]["params"] == {"file": gen, "database": gen + 5}
    assert {a["id"] for a in alerts.rows[0]["actions"]} == {"keep", "backup"}
    assert alerts.rows[0]["actions"][0]["route"] == registry_boot.RESOLVE_ROUTE
    before = _files_bytes(w.state)
    try:
        owner_state.forget(w.state, "xtalk")
        raise AssertionError("a write was accepted in a read-only boot")
    except owner_state.StateWriteFailed:
        pass
    assert _files_bytes(w.state) == before
    assert owner_state.stored_entry(w.state, "huddle") == JOE_STATE["huddle"]
    registry_store.clear_read_only(w.state)


def test_keeping_the_older_file_lifts_read_only_and_goes_above_the_marker(tmp_path):
    w = migrated(tmp_path)
    gen = registry_store.read_generation(w.state)
    set_marker(w.state, gen + 5)
    boot(w.state, Alerts())
    assert registry_boot.resolve(w.state, registry_boot.CHOICE_KEEP) is True
    assert registry_store.read_only_reason(w.state) is None
    assert registry_store.read_generation(w.state) == gen + 6 == registry_store.read_marker(w.state).generation
    assert owner_state.forget(w.state, "xtalk") is True
    assert boot(w.state, Alerts()).action == registry_boot.A_NORMAL


def test_using_the_backup_restores_the_bak_copy_and_lifts_read_only(tmp_path):
    w = migrated(tmp_path)
    owner_state.forget(w.state, "xtalk")
    gen = registry_store.read_generation(w.state)
    set_marker(w.state, gen + 3)
    boot(w.state, Alerts())
    assert registry_boot.resolve(w.state, registry_boot.CHOICE_BACKUP) is True
    assert registry_store.read_only_reason(w.state) is None
    assert "xtalk" in registry_store.load_registry(w.state)[0]["items"]
    assert registry_store.read_generation(w.state) > gen + 3


def test_a_file_higher_than_the_marker_is_accepted_and_the_marker_follows(tmp_path):
    w = migrated(tmp_path)
    gen = registry_store.read_generation(w.state)
    set_marker(w.state, gen - 1)
    alerts = Alerts()
    assert boot(w.state, alerts).action == registry_boot.A_NORMAL and alerts.rows == []
    assert registry_store.read_marker(w.state).generation == gen and registry_store.read_generation(w.state) == gen


def test_a_newer_legacy_state_json_is_ignored_once_registry_json_is_canonical(tmp_path):
    w = migrated(tmp_path)
    legacy = w.state / "cplugs" / "state.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"cplugs": {"huddle": {"enabled": False}, "brandnew": {"enabled": True}}}))
    future = time.time() + 10
    os.utime(legacy, (future, future))
    outcome = boot(w.state, Alerts())
    assert outcome.action == registry_boot.A_NORMAL
    fresh = registry_store.load_registry(w.state)[0]
    assert fresh["items"]["huddle"]["enabled"] is True
    assert "brandnew" not in fresh["items"]


def test_an_unreadable_registry_json_falls_back_to_the_bak_copy(tmp_path):
    w = migrated(tmp_path)
    owner_state.forget(w.state, "xtalk")
    registry_store.registry_path(w.state).write_text("{ torn")
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    assert outcome.action == registry_boot.A_RESTORED and outcome.detail == "registry.json.bak"
    assert registry_store.is_migrated(registry_store.load_registry(w.state)[0])
    assert [a["key"] for a in alerts.rows] == [registry_boot.KEY_RESTORED]
    assert registry_store.read_generation(w.state) == registry_store.read_marker(w.state).generation


def test_with_no_bak_the_newest_migration_backup_is_used(tmp_path):
    w = migrated(tmp_path)
    backup = registry_store.backup_dir(w.state, 1)
    backup.mkdir(parents=True, exist_ok=True)
    (backup / registry_store.REGISTRY_FILE).write_bytes(registry_store.registry_path(w.state).read_bytes())
    registry_store.registry_path(w.state).write_text("{ torn")
    registry_store.registry_path(w.state).with_suffix(".json.bak").unlink(missing_ok=True)
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    assert outcome.action == registry_boot.A_RESTORED and outcome.detail == "migration-backup-1"
    assert owner_state.stored_entry(w.state, "huddle") == JOE_STATE["huddle"]
    assert registry_store.is_migrated(registry_store.load_registry(w.state)[0])


def test_a_missing_plugins_json_with_a_marker_is_never_a_first_boot(tmp_path):
    w = migrated(tmp_path)
    backup = registry_store.backup_dir(w.state, 1)
    backup.mkdir(parents=True, exist_ok=True)
    (backup / registry_store.REGISTRY_FILE).write_bytes(registry_store.registry_path(w.state).read_bytes())
    registry_store.registry_path(w.state).unlink()
    registry_store.registry_path(w.state).with_suffix(".json.bak").unlink(missing_ok=True)
    outcome = boot(w.state, Alerts())
    assert outcome.action == registry_boot.A_RESTORED


def test_when_nothing_reads_the_boot_is_read_only_and_refuses_writes(tmp_path):
    w = migrated(tmp_path)
    registry_store.registry_path(w.state).write_text("{ torn")
    registry_store.registry_path(w.state).with_suffix(".json.bak").write_text("{ torn")
    alerts = Alerts()
    outcome = boot(w.state, alerts)
    assert outcome.action == registry_boot.A_READ_ONLY and outcome.read_only
    assert [(a["key"], a["severity"]) for a in alerts.rows] == [(registry_boot.KEY_READ_ONLY, "error")]
    before = _files_bytes(w.state)
    assert registry_store.save_document(w.state, registry_store.new_document(), log_event="t") is False
    assert _files_bytes(w.state) == before and registry_store.describe(w.state)[1] == registry_store.SOURCE_READ_ONLY
    registry_store.clear_read_only(w.state)


def test_a_lock_held_by_another_process_is_a_read_only_boot(tmp_path, monkeypatch):
    w = migrated(tmp_path)
    monkeypatch.setattr(registry_store, "LOCK_WAIT_SECONDS", 0.05)

    def busy(path, timeout):
        raise registry_store.RegistryBusy("another process holds the plugin registry lock")

    monkeypatch.setattr(registry_store, "_take_flock", busy)
    outcome = boot(w.state, Alerts())
    monkeypatch.undo()
    assert outcome.action == registry_boot.A_READ_ONLY and outcome.detail == "registry_busy"
    registry_store.clear_read_only(w.state)
