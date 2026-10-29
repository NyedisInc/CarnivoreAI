
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.core.inventory import registry, registry_side, state_files
from src.core.inventory.claims import EXCLUSION_KINDS, GAP


def test_every_data_file_the_world_wrote_is_accounted_for(seeded: SimpleNamespace) -> None:
    assert state_files.unaccounted(seeded.state) == []


def test_a_stray_database_or_json_store_fails_the_walk(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    for rel in ("by_session.db", "notes/per-project.json", "notes/log.jsonl", "carnivore.db", "bookmarks.db"):
        (tmp_path / rel).write_text("x")
    assert state_files.unaccounted(tmp_path) == ["by_session.db", "notes/log.jsonl", "notes/per-project.json"]


def test_a_file_under_a_claimed_or_excluded_folder_is_accounted_for(tmp_path: Path) -> None:
    for rel in ("time-machine/unknown/c/p/meta.json", "swarm/settings/3.json", "purge-receipts/r.json", "session-journal/pre-reboot-1.db",
                "swarm/settings/3.txt", "cplugs/crate/jobs/j1.json", "cplugs/crate/extract/x/projects/-a/c.jsonl"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    assert state_files.unaccounted(tmp_path) == []


def test_the_excluded_stores_are_relative_valid_and_not_also_opened() -> None:
    book = registry.book()
    assert all(s.kind in EXCLUSION_KINDS and not s.store.startswith(("/", "..")) and s.reason for s in book.stores)
    assert not [s.store for s in book.stores if s.store in registry_side.SIDE_DBS.values()]


def test_the_known_gaps_are_the_listed_ones() -> None:
    gaps = sorted(s.store for s in registry.book().stores if s.kind == GAP)
    assert gaps == ["company_images/*", "lineage-live.json", "project_images/*", "row_looks.json", "session_metadata.json"]


def test_a_missing_state_folder_is_an_error_not_a_clean_audit(tmp_path: Path) -> None:
    assert state_files.main(["state_files", str(tmp_path / "absent")]) == 2
    assert state_files.main(["state_files", str(tmp_path)]) == 0
