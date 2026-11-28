
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.core.retention import archive, bundles, logs
from src.core.retention.paths import RetentionPaths
from src.core.retention.service import RetentionService
from tests.python.retention.conftest import make_file

needs_zstd = pytest.mark.skipif(shutil.which("zstd", path="/opt/homebrew/bin:/usr/local/bin:/usr/bin") is None, reason="zstd not installed")
DAY = 86_400
MB = 1024 * 1024


def _bundle(root: Path, name: str, age_days: float) -> Path:
    b = root / name
    make_file(b / "Contents" / "MacOS" / "x", 32, age_seconds=age_days * DAY)
    import os, time
    t = time.time() - age_days * DAY
    os.utime(b, (t, t))
    return b


@needs_zstd
def test_keeps_newest_two_across_rollback_and_packed_and_archives_the_rest(roots: RetentionPaths, service: RetentionService) -> None:
    a = _bundle(roots.rollback_dir, "Carnivore 1.0.app", 5)
    b = _bundle(roots.rollback_dir / "packed", "Carnivore 1.1.app", 4)
    c = _bundle(roots.rollback_dir, "Carnivore 1.2.app", 3)
    d = _bundle(roots.rollback_dir / "packed", "Carnivore 1.3.app", 2)
    e = _bundle(roots.rollback_dir, "Carnivore 1.4.app", 1)
    report = service.run(dry_run=False)
    assert [p.exists() for p in (a, b, c, d, e)] == [False, False, False, True, True]
    out = roots.drive_root / "carnivore-installs" / "app-archive"
    assert all((out / f"Carnivore 1.{i}.app.tar.zst").is_file() for i in (0, 1, 2))
    assert report.counts() == {"done": 3}


@needs_zstd
def test_an_existing_verified_archive_is_used_and_not_repacked(roots: RetentionPaths, service: RetentionService) -> None:
    old = _bundle(roots.rollback_dir / "packed", "Carnivore 0.9.app", 9)
    _bundle(roots.rollback_dir, "Carnivore 1.0.app", 2)
    _bundle(roots.rollback_dir, "Carnivore 1.1.app", 1)
    existing = archive.pack_bundle(old, roots.drive_root / "carnivore-installs" / "expired" / "Carnivore 0.9.app.tar.zst")
    stamp = existing.stat().st_mtime_ns
    report = service.run(dry_run=False)
    assert not old.exists() and existing.stat().st_mtime_ns == stamp
    assert not (roots.drive_root / "carnivore-installs" / "app-archive" / "Carnivore 0.9.app.tar.zst").exists()
    assert "existing archive verified" in report.actions[0].detail


@needs_zstd
def test_a_bad_existing_archive_is_not_trusted_and_the_bundle_survives_a_failed_pack(
        roots: RetentionPaths, service: RetentionService, monkeypatch: pytest.MonkeyPatch) -> None:
    old = _bundle(roots.rollback_dir, "Carnivore 0.9.app", 9)
    _bundle(roots.rollback_dir, "Carnivore 1.0.app", 2)
    _bundle(roots.rollback_dir, "Carnivore 1.1.app", 1)
    bad = roots.drive_root / "carnivore-installs" / "app-archive" / "Carnivore 0.9.app.tar.zst"
    bad.write_bytes(b"not an archive")
    monkeypatch.setattr(bundles, "pack_bundle", lambda *_a, **_k: (_ for _ in ()).throw(archive.ArchiveError("pack failed")))
    report = service.run(dry_run=False)
    assert old.exists() and report.actions[0].status == "failed" and bad.read_bytes() == b"not an archive"


def test_bundles_stay_when_the_drive_is_missing(roots: RetentionPaths) -> None:
    from src.config.retention import RetentionConfig
    old = _bundle(roots.rollback_dir, "Carnivore 0.9.app", 9)
    _bundle(roots.rollback_dir, "Carnivore 1.0.app", 2)
    _bundle(roots.rollback_dir, "Carnivore 1.1.app", 1)
    gone = RetentionPaths(roots.state_dir, roots.rollback_dir, roots.menubar_log_dir, roots.drive_root, is_mount=lambda _p: False)
    report = RetentionService(lambda: gone, RetentionConfig).run(False)
    assert old.exists() and [a.status for a in report.actions] == ["skipped"]


def test_logs_under_the_cap_are_left_alone(roots: RetentionPaths, service: RetentionService) -> None:
    make_file(roots.menubar_log_dir / "server.log.1", 1 * MB, age_seconds=DAY)
    assert service.run(dry_run=False).actions == []


def test_logs_over_the_cap_roll_oldest_first_and_never_the_live_file(roots: RetentionPaths, tmp_path: Path) -> None:
    from src.config.retention import RetentionConfig
    d = roots.menubar_log_dir
    live = make_file(d / "server.log", 20 * MB, age_seconds=5)
    quiet_unrotated = make_file(d / "main.log", 20 * MB, age_seconds=30 * DAY)
    old = make_file(d / "server.log.3", 20 * MB, age_seconds=9 * DAY)
    mid = make_file(d / "server.log.2", 20 * MB, age_seconds=5 * DAY)
    new = make_file(d / "server.log.1", 20 * MB, age_seconds=2 * DAY)
    report = RetentionService(lambda: roots, lambda: RetentionConfig(menubar_log_cap_mb=50)).run(False)
    assert [old.exists(), mid.exists(), new.exists()] == [False, False, False]
    assert live.exists() and quiet_unrotated.exists()
    assert report.counts() == {"done": 3}
    dest = roots.drive_root / "manual-backups" / "carnivore-menubar-logs"
    assert len(list(dest.iterdir())) == 3


def test_log_plan_stops_as_soon_as_the_folder_fits(roots: RetentionPaths) -> None:
    d = roots.menubar_log_dir
    make_file(d / "server.log", 1 * MB, age_seconds=5)
    for i, age in ((1, 2), (2, 5), (3, 9)):
        make_file(d / f"server.log.{i}", 10 * MB, age_seconds=age * DAY)
    plan = logs.plan(d, roots.drive_root, cap_mb=25)
    assert [a.source.name for a in plan] == ["server.log.3"]
