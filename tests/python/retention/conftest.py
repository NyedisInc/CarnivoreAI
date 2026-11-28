
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from src.config.retention import RetentionConfig
from src.core.retention.paths import RetentionPaths
from src.core.retention.service import RetentionService


@pytest.fixture(autouse=True)
def no_real_home(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> Path:
        raise AssertionError("retention touched the real home directory")
    monkeypatch.setattr(Path, "home", boom)
    monkeypatch.delenv("CARNIVORE_ROLLBACK_DIR", raising=False)


@pytest.fixture()
def roots(tmp_path: Path) -> RetentionPaths:
    drive = tmp_path / "Backup"
    (drive / "carnivore-installs" / "app-archive").mkdir(parents=True)
    (drive / "carnivore-installs" / "expired").mkdir(parents=True)
    (drive / "README-FILING.md").write_text("filing rules")
    paths = RetentionPaths(state_dir=tmp_path / "state", rollback_dir=tmp_path / "rollback",
                           menubar_log_dir=tmp_path / "logs", drive_root=drive, is_mount=lambda _p: True)
    for d in (paths.state_dir, paths.rollback_dir / "packed", paths.menubar_log_dir):
        d.mkdir(parents=True)
    return paths


@pytest.fixture()
def service(roots: RetentionPaths) -> RetentionService:
    return RetentionService(lambda: roots, lambda: RetentionConfig())


def make_file(path: Path, size: int = 10, age_seconds: float = 0, content: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if content is not None else os.urandom(size))
    t = time.time() - age_seconds
    os.utime(path, (t, t))
    return path
