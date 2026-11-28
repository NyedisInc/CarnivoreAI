
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.retention import RetentionConfig
from src.core.retention import transfer
from src.core.retention.errors import CopyVerifyError, SourceChangedError
from src.core.retention.paths import RetentionPaths
from src.core.retention.service import RetentionService
from tests.python.retention.conftest import make_file

DAY = 86_400


def _backups(state: Path) -> list[Path]:
    out = [make_file(state / f"carnivore.db.bak-v{n}-2026110{n}T000000Z.nobackup", 64, age_seconds=(6 - n) * DAY) for n in range(1, 6)]
    for keep in ("carnivore.db", "carnivore.online-backup.db"):
        make_file(state / keep, 32, age_seconds=9 * DAY)
    (state / "vault").mkdir()
    make_file(state / "vault" / "x.bin", 8, age_seconds=9 * DAY)
    return out


def test_keeps_the_newest_two_and_moves_the_rest_verified(roots: RetentionPaths, service: RetentionService) -> None:
    made = _backups(roots.state_dir)
    contents = {p.name: p.read_bytes() for p in made}
    report = service.run(dry_run=False)
    left = sorted(p.name for p in roots.state_dir.glob("*.nobackup"))
    assert left == sorted(p.name for p in made[-2:])
    dest = roots.drive_root / "manual-backups" / "carnivore-db"
    for p in made[:3]:
        assert (dest / p.name).read_bytes() == contents[p.name]
    assert report.counts() == {"done": 3}
    for protected in ("carnivore.db", "carnivore.online-backup.db", "vault/x.bin"):
        assert (roots.state_dir / protected).exists()


def test_a_dry_run_reports_and_changes_nothing(roots: RetentionPaths, service: RetentionService) -> None:
    made = _backups(roots.state_dir)
    report = service.run(dry_run=True)
    assert report.counts() == {"planned": 3} and all(p.exists() for p in made)
    assert not (roots.drive_root / "manual-backups").exists()


def test_drive_not_mounted_moves_nothing(roots: RetentionPaths) -> None:
    made = _backups(roots.state_dir)
    unmounted = RetentionPaths(roots.state_dir, roots.rollback_dir, roots.menubar_log_dir, roots.drive_root, is_mount=lambda _p: False)
    report = RetentionService(lambda: unmounted, RetentionConfig).run(False)
    assert not report.drive_ready and "not mounted" in report.drive_detail
    assert all(a.status == "skipped" for a in report.actions) and len(report.actions) == 3
    assert all(p.exists() for p in made)


def test_a_mounted_volume_that_is_not_the_backup_drive_moves_nothing(roots: RetentionPaths, service: RetentionService) -> None:
    made = _backups(roots.state_dir)
    (roots.drive_root / "README-FILING.md").unlink()
    report = service.run(dry_run=False)
    assert not report.drive_ready and "not the expected backup volume" in report.drive_detail
    assert all(p.exists() for p in made)


def test_source_is_removed_only_after_the_copy_verifies(roots: RetentionPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = make_file(tmp_path / "a.nobackup", 128)
    dest = roots.drive_root / "manual-backups" / "carnivore-db" / "a.nobackup"
    seen: dict[str, bool] = {}
    real = transfer.sha256_of

    def corrupt(path: Path) -> str:
        seen["source_alive_during_verify"] = src.exists()
        return "0" * 64 if path.name.endswith(".partial") else real(path)

    monkeypatch.setattr(transfer, "sha256_of", corrupt)
    with pytest.raises(CopyVerifyError):
        transfer.move_file_verified(src, dest)
    assert seen["source_alive_during_verify"] and src.exists() and not dest.exists()
    assert not list(dest.parent.glob("*.partial"))


def test_a_source_that_changes_mid_copy_is_kept(roots: RetentionPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = make_file(tmp_path / "live.log.1", 128)
    real = transfer._copy_hashing

    def copy_then_append(s: Path, partial: Path) -> str:
        digest = real(s, partial)
        with s.open("ab") as handle:
            handle.write(b"more")
        return digest

    monkeypatch.setattr(transfer, "_copy_hashing", copy_then_append)
    with pytest.raises(SourceChangedError):
        transfer.move_file_verified(src, roots.drive_root / "x" / "live.log.1")
    assert src.exists()


def test_an_existing_drive_file_is_never_overwritten(roots: RetentionPaths, tmp_path: Path) -> None:
    src = make_file(tmp_path / "a.nobackup", 16)
    taken = make_file(roots.drive_root / "d" / "a.nobackup", 4, content=b"keep")
    final = transfer.move_file_verified(src, taken)
    assert taken.read_bytes() == b"keep" and final.name == "a-2.nobackup" and not src.exists()


def test_protected_names_are_refused(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="protected"):
        transfer.refuse_protected(tmp_path / "claude-code-local" / "x")
