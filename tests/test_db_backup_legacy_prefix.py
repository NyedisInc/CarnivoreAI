
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core import db_backup
from src.core import product_identity




def test_current_prefix_backup_name_matches() -> None:
    match = db_backup.BACKUP_NAME_RE.match(
        "carnivore.db.bak-v3-20260921T090000Z"
    )
    assert match is not None
    assert match.group("version") == "3"
    assert match.group("stamp") == "20260921T090000Z"
    assert match.group("seq") is None


def test_legacy_prefix_backup_name_matches() -> None:
    match = db_backup.BACKUP_NAME_RE.match(
        "cloude.db.bak-v1-20260818T090000Z"
    )
    assert match is not None
    assert match.group("version") == "1"
    assert match.group("stamp") == "20260818T090000Z"


def test_legacy_prefix_backup_name_with_collision_suffix_matches() -> None:
    match = db_backup.BACKUP_NAME_RE.match(
        "cloude.db.bak-v1-20260818T090000Z-2"
    )
    assert match is not None
    assert match.group("seq") == "2"


def test_an_unrelated_filename_does_not_match() -> None:
    assert db_backup.BACKUP_NAME_RE.match("something-else.db.bak-v1-20260818T090000Z") is None
    assert db_backup.BACKUP_NAME_RE.match("cloude.db") is None
    assert db_backup.BACKUP_NAME_RE.match("carnivore.db") is None


def test_the_literal_dot_in_either_prefix_is_not_a_wildcard() -> None:
    assert db_backup.BACKUP_NAME_RE.match("cloudeXdb.bak-v1-20260818T090000Z") is None
    assert db_backup.BACKUP_NAME_RE.match("carnivoreXdb.bak-v1-20260818T090000Z") is None




def test_backup_prefix_reads_from_product_identity() -> None:
    assert db_backup.BACKUP_PREFIX == product_identity.DB_BACKUP_PREFIX
    assert db_backup.BACKUP_PREFIX == "carnivore.db.bak-v"


def test_a_new_backup_filename_always_uses_the_current_prefix() -> None:
    name = db_backup.backup_filename(
        4, when=datetime(2026, 9, 21, 9, 0, 0, tzinfo=timezone.utc)
    )
    assert name == (
        "carnivore.db.bak-v4-20260921T090000Z" + db_backup.BACKUP_SUFFIX
    )
    assert name.startswith(product_identity.DB_BACKUP_PREFIX)
    assert name.endswith(db_backup.BACKUP_SUFFIX)




def test_list_backups_finds_both_prefixes_on_a_real_directory(
    tmp_path: Path,
) -> None:
    legacy_names = [
        "cloude.db.bak-v1-20260101T000000Z",
        "cloude.db.bak-v2-20260201T000000Z",
    ]
    current_names = [
        "carnivore.db.bak-v3-20260921T090000Z",
    ]
    for name in legacy_names + current_names:
        (tmp_path / name).write_text("not a real sqlite file, just a name probe")
    (tmp_path / "cloude.db.bak-vX-not-a-real-stamp").write_text("junk")

    found = {p.name for p in db_backup.list_backups(tmp_path)}

    assert found == set(legacy_names) | set(current_names)


def test_list_backups_orders_newest_first_across_both_prefixes(
    tmp_path: Path,
) -> None:
    older = "cloude.db.bak-v1-20260101T000000Z"
    newer = "carnivore.db.bak-v2-20260901T000000Z"
    (tmp_path / older).write_text("x")
    (tmp_path / newer).write_text("x")

    found = db_backup.list_backups(tmp_path)

    assert [p.name for p in found] == [newer, older]


def test_prune_backups_protects_recent_legacy_backups_too(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    names = [
        "cloude.db.bak-v1-20260101T000000Z",
        "cloude.db.bak-v2-20260201T000000Z",
        "carnivore.db.bak-v3-20260901T000000Z",
    ]
    for name in names:
        (tmp_path / name).write_text("x")

    deleted = db_backup.prune_backups(
        tmp_path, keep_versions=5, keep_days=90, now=now
    )

    assert deleted == []
    for name in names:
        assert (tmp_path / name).exists(), f"{name} must not have been pruned"


def test_prune_backups_can_still_delete_an_old_legacy_backup(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    old_legacy = [
        f"cloude.db.bak-v{i}-2020010{i}T000000Z" for i in range(1, 7)
    ]
    for name in old_legacy:
        (tmp_path / name).write_text("x")

    deleted = db_backup.prune_backups(
        tmp_path, keep_versions=5, keep_days=1, now=now
    )

    assert len(deleted) == 1
    assert deleted[0].name == old_legacy[0], (
        "the OLDEST backup (by embedded timestamp) must be the one pruned"
    )
    assert not deleted[0].exists()


def test_default_retention_keeps_exactly_the_newest_two_and_sweeps_sidecars(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    names = []
    for i in range(50):
        stamp = (now - timedelta(days=i * 0.25)).strftime("%Y%m%dT%H%M%SZ")
        names.append(f"carnivore.db.bak-v{i}-{stamp}.nobackup")
    for name in names:
        (tmp_path / name).write_text("x")
        (tmp_path / (name + "-shm")).write_text("x")
        (tmp_path / (name + "-wal")).write_text("x")
    orphan = "carnivore.db.bak-v0-20200101T000000Z.nobackup-wal"
    (tmp_path / orphan).write_text("x")
    for live in ("carnivore.db", "carnivore.db-wal", "carnivore.db-shm", "config.json"):
        (tmp_path / live).write_text("x")

    deleted = db_backup.prune_backups(tmp_path, now=now)

    kept = set(names[:2])
    assert len(kept) == 2 and len(deleted) == (50 - 2) * 3 + 1, "population must be non-empty"
    for name in names:
        for suffix in ("", "-shm", "-wal"):
            assert (tmp_path / (name + suffix)).exists() == (name in kept), name + suffix
    assert not (tmp_path / orphan).exists()
    for live in ("carnivore.db", "carnivore.db-wal", "carnivore.db-shm", "config.json"):
        assert (tmp_path / live).exists()
