
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.core.widget_placement.retired_widgets import RENAMED_WIDGETS
from src.cplugs.devwidgetlab.drafts import renames, store

WIDGETS_JSON = Path(__file__).resolve().parents[4] / "src" / "data" / "widgets.json"


def _draft(storage: Path, slug: str, widget: str, **extra: Any) -> Path:
    folder = storage / "drafts" / slug
    (folder / "files" / "web" / "src").mkdir(parents=True)
    (folder / "files" / "web" / "src" / "Cell.svelte").write_text("<p>mine</p>\n")
    (folder / "BRIEF.md").write_text("brief\n")
    record: Dict[str, Any] = {"schema": 1, "slug": slug, "kind": "revision", "widget": widget, "title": slug, "created": "2026-10-19T14:02:27",
                              "state": "built", "base_sha": "7d68db55c626", "session": None, **extra}
    (folder / "draft.json").write_text(json.dumps(record, indent=2) + "\n")
    return folder


def _snapshot(folder: Path) -> Dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file() and p.name not in ("draft.json", renames.BACKUP_NAME)}


def test_a_record_naming_a_renamed_widget_resolves_to_the_current_id_and_that_id_is_declared(tmp_path: Path) -> None:
    declared = {row["id"] for row in json.loads(WIDGETS_JSON.read_text())["widgets"]}
    for old, new in RENAMED_WIDGETS.items():
        folder = _draft(tmp_path, "d-" + old.split(".")[1], old)
        assert store.read_record(folder)["widget"] == new
        assert new in declared and old not in declared
    keyed = _draft(tmp_path, "keyed", "core.huddle-all:i2")
    assert store.read_record(keyed)["widget"] == "core.task-manager-all:i2"


def test_the_start_migration_rewrites_the_record_once_with_a_backup_and_leaves_every_file_alone(tmp_path: Path) -> None:
    folder = _draft(tmp_path, "task-manager", "core.huddle-all", target="core.huddle-list")
    other = _draft(tmp_path, "pulse", "core.pulse")
    new_draft = _draft(tmp_path, "closed-tasks", "core.closed-tasks", kind="new")
    kept = {f.name: _snapshot(f) for f in (folder, other, new_draft)}
    original = (folder / "draft.json").read_text()
    other_text = (other / "draft.json").read_text()

    assert renames.migrate_records(tmp_path) == ["task-manager"]
    record = json.loads((folder / "draft.json").read_text())
    assert record["widget"] == "core.task-manager-all" and record["target"] == "core.task-list"
    assert (folder / renames.BACKUP_NAME).read_text() == original
    assert not (other / renames.BACKUP_NAME).exists() and (other / "draft.json").read_text() == other_text
    assert {f.name: _snapshot(f) for f in (folder, other, new_draft)} == kept

    assert renames.migrate_records(tmp_path) == []
    assert (folder / renames.BACKUP_NAME).read_text() == original


def test_an_unreadable_record_is_left_alone(tmp_path: Path) -> None:
    folder = _draft(tmp_path, "broken", "core.huddle")
    (folder / "draft.json").write_text("{not json")
    assert renames.migrate_records(tmp_path) == []
    assert (folder / "draft.json").read_text() == "{not json" and not (folder / renames.BACKUP_NAME).exists()


def test_a_draft_built_against_an_older_checkout_is_stale_and_not_an_error(tmp_path: Path, monkeypatch) -> None:
    folder = _draft(tmp_path, "tasks", "core.huddle-list", base_sha="7d68db55c626")
    monkeypatch.setattr(store, "root_of", lambda _folder: tmp_path)
    monkeypatch.setattr(store, "head_sha", lambda _repo: "73bdd18f67a5")
    shown = store.summary(folder)
    assert shown["stale"] is True and shown["state"] == "built" and shown["widget"] == "core.task-list"
