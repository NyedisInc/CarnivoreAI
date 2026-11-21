
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

TEMP_REPO_HEAD_FILE = "HEAD"


def test_no_git_variable_is_visible_inside_a_test() -> None:
    leaked = sorted(key for key in os.environ if key.startswith("GIT_"))
    assert leaked == [], leaked


def test_a_test_can_still_set_its_own_git_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    assert os.environ["GIT_AUTHOR_NAME"] == "t"


def test_temp_repo_init_does_not_touch_an_inherited_git_dir(tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    assert (tmp_path / ".git" / TEMP_REPO_HEAD_FILE).is_file()
