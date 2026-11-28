
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.plugins.host import plugin_fold, registry_store, renamed, renamed_entry, runtime, state as owner_state, swarm_default_migration
from tests.python.cplugs.taskmanager.test_task_manager_flip_boot import ENTRY, cplugs, installed  # noqa: F401

PLUMBING = {"work"}
OFF_ENTRY = {"kind": "feature", "enabled": False, "grants": [], "settings": {"nudgeMinutes": 30}, "revision": 2, "digest": "d1", "updated_at": 1.5}


def manifest() -> Any:
    return runtime.find("taskmanager").manifest


def seed(state: Path, entry: Dict[str, Any]) -> None:
    doc = registry_store.new_document()
    doc["items"]["huddle"] = dict(entry)
    registry_store.registry_path(state).write_text(json.dumps(doc), encoding="utf-8")


def boot_steps(state: Path) -> renamed_entry.RenameOutcome:
    outcome = renamed_entry.migrate(state)
    swarm_default_migration.migrate(state, False)
    plugin_fold.migrate(state)
    return outcome


def block_record(state: Path) -> Path:
    blocker = renamed_entry.carried_path(state)
    blocker.mkdir()
    return blocker


def test_a_failing_carry_does_not_turn_an_off_owner_on(installed: Path) -> None:  # noqa: F811
    seed(installed, OFF_ENTRY)
    block_record(installed)
    assert boot_steps(installed).failed is True
    got = owner_state.get(installed, manifest())
    assert got.enabled is False and set(got.grants) <= PLUMBING and got.settings == {"nudgeMinutes": 30}
    assert "taskmanager" not in cplugs(installed)


def test_a_failing_carry_keeps_an_on_owner_on_with_the_old_grants(installed: Path) -> None:  # noqa: F811
    blocker = block_record(installed)
    assert boot_steps(installed).failed is True
    got = owner_state.get(installed, manifest())
    assert got.enabled is True and set(got.grants) == set(ENTRY["grants"]) | PLUMBING and got.stored is False
    blocker.rmdir()
    assert renamed_entry.migrate(installed).copied == ["huddle"]
    assert owner_state.get(installed, manifest()).stored is True


def test_a_carry_recorded_as_done_is_not_pending(installed: Path) -> None:  # noqa: F811
    renamed_entry.migrate(installed)
    assert owner_state.carry_state(installed, manifest()) == ""
    assert owner_state.carry_pending(installed, manifest()) is False


def test_a_store_restored_from_backup_is_off_and_never_waits_forever(installed: Path) -> None:  # noqa: F811
    renamed_entry.migrate(installed)
    seed(installed, OFF_ENTRY)
    assert owner_state.carry_state(installed, manifest()) == owner_state.CARRY_STRANDED
    boot_steps(installed)
    got = owner_state.get(installed, manifest())
    assert got.enabled is False and got.grants == ()
    assert "taskmanager" not in cplugs(installed), "a default was written over the entry the revert switch needs absent"
    assert renamed_entry.revert(installed).forgotten == ["huddle"]
    assert renamed_entry.migrate(installed).copied == ["huddle"]
    assert cplugs(installed)["taskmanager"] == OFF_ENTRY


def test_a_stuck_carry_raises_an_owner_alert(installed: Path) -> None:  # noqa: F811
    raised: List[str] = []
    sink = lambda key, **kw: raised.append(f"{key}|{kw['detail_key']}")  # noqa: E731
    defs = runtime.definitions()
    assert renamed.alert_stuck_carries(installed, defs, sink) == ["taskmanager"] and raised == ["cplug_rename.stuck.taskmanager|app_alert.cplug_rename.stuck.detail_pending"]
    renamed_entry.migrate(installed)
    assert renamed.alert_stuck_carries(installed, defs, sink) == [] and len(raised) == 1
    seed(installed, OFF_ENTRY)
    assert renamed.alert_stuck_carries(installed, defs, sink) == ["taskmanager"] and raised[-1].endswith("detail_stranded")


def test_a_manifest_with_no_renamed_from_field_reads_its_default(tmp_path: Path) -> None:
    from types import SimpleNamespace

    stub = SimpleNamespace(id="outside", tier="catalog", permissions=(), default_enabled=None)
    assert owner_state.get(tmp_path, stub).enabled is False
    assert owner_state.carry_state(tmp_path, stub) == ""
