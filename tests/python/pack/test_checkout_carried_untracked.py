import subprocess

import pytest

from src.core.pack.migrate import code


def _g(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


def _repo(tmp_path):
    _g(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("1")
    _g(tmp_path, "add", "a.txt")
    _g(tmp_path, "commit", "-q", "-m", "one")
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    return head


def test_untracked_file_does_not_block_checkout(tmp_path):
    head = _repo(tmp_path)
    (tmp_path / ".prompt_history").mkdir()
    (tmp_path / ".prompt_history" / "x").write_text("p")
    code._checkout_carried(str(tmp_path), "peer", "main", head, air_gap=False)


def test_tracked_change_still_blocks(tmp_path):
    head = _repo(tmp_path)
    (tmp_path / "a.txt").write_text("2")
    with pytest.raises(code.CodeError):
        code._checkout_carried(str(tmp_path), "peer", "main", head, air_gap=False)
