
from __future__ import annotations

from pathlib import Path

from src.core import db
from src.core import product_identity


def test_fresh_state_dir_resolves_to_the_current_name(tmp_path: Path) -> None:
    resolved = db.db_path_for(tmp_path)

    assert resolved == tmp_path / "carnivore.db"
    assert not resolved.exists()


def test_existing_legacy_file_is_never_the_answer(tmp_path: Path) -> None:
    (tmp_path / "cloude.db").write_text("legacy")

    assert db.db_path_for(tmp_path) == tmp_path / "carnivore.db"


def test_current_name_wins_when_both_exist(tmp_path: Path) -> None:
    (tmp_path / "cloude.db").write_text("legacy")
    (tmp_path / "carnivore.db").write_text("current")

    resolved = db.db_path_for(tmp_path)

    assert resolved == tmp_path / "carnivore.db"
    assert (tmp_path / "cloude.db").read_text() == "legacy", (
        "resolving must never delete or rewrite the legacy copy"
    )


def test_db_filename_constant_reads_from_product_identity() -> None:
    assert db.DB_FILENAME == product_identity.DB_FILENAME == "carnivore.db"


def test_this_phase_never_renames_a_live_database(tmp_path: Path) -> None:
    legacy = tmp_path / "cloude.db"
    legacy.write_text("live data")

    db.db_path_for(tmp_path)
    db.db_path_for(tmp_path)

    assert legacy.exists()
    assert legacy.read_text() == "live data"
    assert not (tmp_path / "carnivore.db").exists()
