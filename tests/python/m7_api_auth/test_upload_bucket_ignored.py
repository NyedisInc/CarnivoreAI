
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.api import uploads


def test_the_bucket_carries_a_gitignore_that_ignores_everything(tmp_path: Path) -> None:
    saved = uploads.save_upload_to_session_dir(b"secret bytes", "note.txt", str(tmp_path))
    ignore = saved.parent / ".gitignore"
    assert ignore.read_text().strip() == "*"
    assert (ignore.stat().st_mode & 0o777) == 0o600


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_sees_nothing_to_add(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    uploads.save_upload_to_session_dir(b"secret bytes", "note.txt", str(tmp_path))
    status = subprocess.run(["git", "-C", str(tmp_path), "status", "--porcelain", "--untracked-files=all"],
                            check=True, capture_output=True, text=True).stdout
    assert status.strip() == ""


def test_a_second_upload_keeps_the_existing_gitignore(tmp_path: Path) -> None:
    first = uploads.save_upload_to_session_dir(b"a", "a.txt", str(tmp_path))
    (first.parent / ".gitignore").write_text("*\n# owner edit\n")
    uploads.save_upload_to_session_dir(b"b", "b.txt", str(tmp_path))
    assert "# owner edit" in (first.parent / ".gitignore").read_text()


def _age(path: Path, seconds: float) -> None:
    import os
    import time

    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_the_sweeper_never_prunes_the_gitignore_while_uploads_remain(tmp_path: Path) -> None:
    import time

    from src.core import upload_sweeper

    old = uploads.save_upload_to_session_dir(b"old", "old.txt", str(tmp_path))
    fresh = uploads.save_upload_to_session_dir(b"new", "new.txt", str(tmp_path))
    ignore = old.parent / ".gitignore"
    _age(old, 7200)
    _age(ignore, 7200)
    upload_sweeper._prune_base(str(tmp_path), time.time() - 3600)
    assert not old.exists() and fresh.exists()
    assert ignore.exists(), "pruning the ignore file would expose the remaining uploads to git add -A"


def test_the_sweeper_removes_the_bucket_when_only_the_gitignore_is_left(tmp_path: Path) -> None:
    import time

    from src.core import upload_sweeper

    old = uploads.save_upload_to_session_dir(b"old", "old.txt", str(tmp_path))
    bucket = old.parent
    _age(old, 7200)
    _age(bucket / ".gitignore", 7200)
    upload_sweeper._prune_base(str(tmp_path), time.time() - 3600)
    assert not bucket.exists()
