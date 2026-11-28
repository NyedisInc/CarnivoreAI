
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional, Set

import pytest

from src.config.retention import RetentionConfig
from src.core.retention import scratch
from src.core.retention.errors import ProtectedPathError
from src.core.retention.paths import RetentionPaths
from src.core.retention.service import RetentionService
from tests.python.retention.conftest import make_file

HOUR = 3600
OLD = 48 * HOUR


def _paths(roots: RetentionPaths, tmp_path: Path, live: Optional[Set[str]] = frozenset()) -> RetentionPaths:
    root = tmp_path / "claude-501"
    root.mkdir(exist_ok=True)
    return RetentionPaths(roots.state_dir, roots.rollback_dir, roots.menubar_log_dir, roots.drive_root,
                          is_mount=lambda _p: True, scratch_root=root, live_sessions=lambda: live)


def _session(paths: RetentionPaths, uuid: str, age: float = OLD) -> Path:
    base = paths.scratch_root / "-proj" / uuid
    make_file(base / "scratchpad" / "a.txt", 5, age_seconds=age)
    make_file(base / "scratchpad" / "sub" / "b.txt", 5, age_seconds=age)
    make_file(base / "tasks" / "t.json", 5, age_seconds=age)
    return base


def _svc(paths: RetentionPaths) -> RetentionService:
    return RetentionService(lambda: paths, RetentionConfig)


def test_an_idle_finished_session_has_its_scratchpad_contents_cleared_and_tasks_kept(roots, tmp_path) -> None:
    p = _paths(roots, tmp_path)
    base = _session(p, "u-done")
    report = _svc(p).run(dry_run=False)
    assert report.counts() == {"done": 1}
    assert base.is_dir() and (base / "scratchpad").is_dir() and list((base / "scratchpad").iterdir()) == []
    assert (base / "tasks" / "t.json").exists()


def test_a_running_session_is_kept(roots, tmp_path) -> None:
    p = _paths(roots, tmp_path, live=frozenset({"u-live"}))
    base = _session(p, "u-live")
    assert _svc(p).run(dry_run=False).actions == []
    assert (base / "scratchpad" / "a.txt").exists()


def test_an_unreadable_registry_clears_nothing(roots, tmp_path) -> None:
    p = _paths(roots, tmp_path, live=None)
    base = _session(p, "u-x")
    assert _svc(p).run(dry_run=False).actions == []
    assert (base / "scratchpad" / "a.txt").exists()


def test_a_recent_change_anywhere_in_the_folder_keeps_it(roots, tmp_path) -> None:
    p = _paths(roots, tmp_path)
    base = _session(p, "u-recent")
    make_file(base / "tasks" / "fresh.json", 5, age_seconds=HOUR)
    assert _svc(p).run(dry_run=False).actions == []
    assert (base / "scratchpad" / "a.txt").exists()


def test_a_dry_run_lists_and_changes_nothing(roots, tmp_path) -> None:
    p = _paths(roots, tmp_path)
    base = _session(p, "u-dry")
    report = _svc(p).run(dry_run=True)
    assert report.counts() == {"planned": 1} and report.actions[0].bytes == 10
    assert (base / "scratchpad" / "a.txt").exists() and (base / "scratchpad" / "sub" / "b.txt").exists()


def test_a_scratchpad_symlinked_outside_the_root_is_refused(roots, tmp_path) -> None:
    p = _paths(roots, tmp_path)
    outside = tmp_path / "outside"
    keep = make_file(outside / "precious.txt", 5, age_seconds=OLD)
    base = p.scratch_root / "-proj" / "u-link"
    base.mkdir(parents=True)
    (base / "scratchpad").symlink_to(outside)
    report = _svc(p).run(dry_run=False)
    assert [a.status for a in report.actions] == ["skipped"] and "refused" in report.actions[0].detail
    assert keep.exists()
    with pytest.raises(ProtectedPathError):
        scratch.apply(report.actions[0], p, 24)
    assert keep.exists()


def test_a_symlink_inside_the_scratchpad_is_unlinked_not_followed(roots, tmp_path) -> None:
    p = _paths(roots, tmp_path)
    base = _session(p, "u-inner")
    outside = tmp_path / "outside"
    keep = make_file(outside / "precious.txt", 5, age_seconds=OLD)
    link = base / "scratchpad" / "escape"
    link.symlink_to(outside)
    old = time.time() - OLD
    os.utime(link, (old, old), follow_symlinks=False)
    _svc(p).run(dry_run=False)
    assert keep.exists() and not link.is_symlink()


def test_a_session_folder_that_is_a_symlink_out_of_the_root_is_refused(roots, tmp_path) -> None:
    p = _paths(roots, tmp_path)
    outside = tmp_path / "elsewhere"
    keep = make_file(outside / "scratchpad" / "x", 5, age_seconds=OLD)
    (p.scratch_root / "-proj").mkdir()
    (p.scratch_root / "-proj" / "u-s").symlink_to(outside)
    report = _svc(p).run(dry_run=False)
    assert all(a.status != "done" for a in report.actions) and keep.exists()


def test_the_default_registry_reader_is_the_existing_one(tmp_path: Path) -> None:
    from src.core.attention.registry_index import live_session_uuids
    from src.core.retention.paths import default_paths
    assert default_paths(tmp_path, home=tmp_path).live_sessions is live_session_uuids
    assert live_session_uuids(str(tmp_path / "nope")) == frozenset()
