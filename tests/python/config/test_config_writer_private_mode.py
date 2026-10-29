
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from src.core import config_writer


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def world_readable_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"a": 1}))
    os.chmod(path, 0o644)
    return path


def test_commit_leaves_config_and_backup_owner_only(world_readable_config: Path) -> None:
    old_umask = os.umask(0o022)
    try:
        outcome = config_writer.commit(world_readable_config, lambda d: {**d, "b": 2})
    finally:
        os.umask(old_umask)
    assert outcome.wrote
    assert _mode(world_readable_config) == 0o600
    assert _mode(world_readable_config.with_name("config.json.bak")) == 0o600


def test_no_temp_file_is_ever_wider_than_owner_only(world_readable_config: Path, monkeypatch) -> None:
    seen: list[int] = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(_mode(Path(src)))
        return real_replace(src, dst)

    monkeypatch.setattr(config_writer.os, "replace", spy)
    config_writer.commit(world_readable_config, lambda d: {**d, "b": 2})
    assert seen and all(m == 0o600 for m in seen)


def test_tighten_existing_fixes_config_and_every_backup_copy(world_readable_config: Path) -> None:
    folder = world_readable_config.parent
    for name in ("config.json.bak", "config.json.bak-20261001"):
        (folder / name).write_text("{}")
        os.chmod(folder / name, 0o644)
    unrelated = folder / "notes.txt"
    unrelated.write_text("x")
    os.chmod(unrelated, 0o644)

    changed = config_writer.tighten_existing(world_readable_config)

    assert len(changed) == 3
    for name in ("config.json", "config.json.bak", "config.json.bak-20261001"):
        assert _mode(folder / name) == 0o600
    assert _mode(unrelated) == 0o644
    assert config_writer.tighten_existing(world_readable_config) == []


def test_tighten_existing_never_follows_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "victim.txt"
    target.write_text("x")
    os.chmod(target, 0o644)
    config = tmp_path / "config.json"
    config.write_text("{}")
    os.chmod(config, 0o600)
    (tmp_path / "config.json.bak").symlink_to(target)

    config_writer.tighten_existing(config)

    assert _mode(target) == 0o644


def test_tighten_existing_tolerates_a_missing_config(tmp_path: Path) -> None:
    assert config_writer.tighten_existing(tmp_path / "config.json") == []
