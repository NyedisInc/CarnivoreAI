
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from src.core.work.capability import WorkCapability
from src.core.work.storage import storage_for
from src.plugins.host import plugin_fold, registry_store, renamed_entry, renamed_files, renamed_files_revert, swarm_default_migration
from src.plugins.taskmanager import files as item_files
from tests.python.work.test_work_open import seeded_copy, work_count

ENTRY = {"kind": "feature", "enabled": True, "grants": ["swarm", "notify"], "settings": {"nudgeMinutes": 30}, "revision": 4, "digest": "d1", "updated_at": 1.5}
FILE_ID = "ab12cd34"
NAME = f"{FILE_ID}-a.png"
DATA = b"\x89PNG not really, but bytes"


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CARNIVORE_STATE_DIR", str(tmp_path))
    seeded_copy(tmp_path)
    (tmp_path / "cplugs" / "huddle" / "files" / "7").mkdir(parents=True)
    (tmp_path / "cplugs" / "huddle" / "files" / "7" / NAME).write_bytes(DATA)
    path = registry_store.registry_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = registry_store.new_document()
    doc["items"]["huddle"] = dict(ENTRY)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def cplugs(state: Path) -> Dict[str, Any]:
    return json.loads(registry_store.registry_path(state).read_text(encoding="utf-8"))["items"]


def boot(state: Path) -> renamed_files.FilesOutcome:
    renamed_entry.migrate(state)
    return renamed_files.migrate(state, free_space=lambda _s: 10**12, alert=lambda key, **kw: None)


def test_the_first_boot_carries_serves_and_reads_the_legacy_db(installed: Path) -> None:
    assert boot(installed).state == {"huddle": "moved"}
    stored = cplugs(installed)
    assert stored["taskmanager"] == ENTRY and stored["huddle"] == ENTRY
    storage = storage_for(installed)
    new_file = installed / "cplugs" / "taskmanager" / "files" / "7" / NAME
    assert item_files.locate(storage, 7, FILE_ID) == new_file and new_file.read_bytes() == DATA
    assert item_files.stored_file(storage, f"files/7/{NAME}") == new_file
    work = WorkCapability(installed)
    work.open()
    assert work_count(work, "SELECT COUNT(*) FROM work_items") == 2
    assert (installed / "cplugs" / "huddle" / "huddle.db").is_file()


def test_a_second_boot_is_a_no_op(installed: Path) -> None:
    boot(installed)
    before = registry_store.registry_path(installed).read_bytes()
    assert boot(installed).state == {"huddle": "done"}
    assert registry_store.registry_path(installed).read_bytes() == before


def test_the_reverse_switch_undoes_the_carry_and_the_move(installed: Path) -> None:
    boot(installed)
    assert renamed_entry.revert(installed).removed == ["huddle"]
    assert "taskmanager" not in cplugs(installed) and cplugs(installed)["huddle"] == ENTRY
    assert renamed_files_revert.revert(installed, app_running=lambda: False).state == {"huddle": "reverted"}
    assert not (installed / "cplugs" / "taskmanager" / "files").exists()
    assert (installed / "cplugs" / "huddle" / "files" / "7" / NAME).read_bytes() == DATA
    assert (installed / "cplugs" / "huddle" / "huddle.db").is_file()


def boot_with_later_steps(state: Path) -> renamed_entry.RenameOutcome:
    outcome = renamed_entry.migrate(state)
    swarm_default_migration.migrate(state, False)
    plugin_fold.migrate(state)
    return outcome


@pytest.mark.parametrize("nudge", [None, {"enabled": False}], ids=["swarm default", "fold too"])
def test_a_failed_carry_is_retried_and_never_overwritten_by_a_later_step(installed: Path, nudge: Any) -> None:
    if nudge is not None:
        doc = json.loads(registry_store.registry_path(installed).read_text(encoding="utf-8"))
        doc["items"]["nudge"] = {"kind": "feature", **nudge}
        registry_store.registry_path(installed).write_text(json.dumps(doc), encoding="utf-8")
    unreadable = renamed_entry.carried_path(installed)
    unreadable.mkdir()
    assert boot_with_later_steps(installed).failed is True
    assert "taskmanager" not in cplugs(installed), "the swarm default or the fold stored an answer for the new id over the old entry"
    unreadable.rmdir()
    assert boot_with_later_steps(installed).copied == ["huddle"]
    carried = cplugs(installed)["taskmanager"]
    assert carried["enabled"] is True and set(ENTRY["grants"]) <= set(carried["grants"]) and carried["settings"]["nudgeMinutes"] == 30
    assert carried["settings"].get("nudgeEnabled") is (None if nudge is None else False)
