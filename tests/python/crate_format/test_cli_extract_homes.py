
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

import pytest

from tests.python.crate_format.helpers import CONV, build_crate
from tests.python.crate_format.test_cli import CHECK, ROOT


def _run(tmp_path: Path, dest: Path, extra: Dict[str, str]) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path / "home"), "PYTHONPATH": str(ROOT),
           "CARNIVORE_STATE_DIR": str(tmp_path / "state"), "TMPDIR": str(tmp_path), **extra}
    crate = build_crate(tmp_path / "a.crate")
    return subprocess.run([sys.executable, "-c", CHECK, "extract", str(crate), CONV, str(dest)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("home,env_name", [(".claude", ""), (".codex", ""), ("profiles/work", "CLAUDE_CONFIG_DIR"),
                                           ("codex-alt", "CODEX_HOME")])
def test_extract_into_a_live_home_is_refused(tmp_path: Path, home: str, env_name: str) -> None:
    live = tmp_path / "home" / home
    (live / "projects").mkdir(parents=True)
    dest = live / "projects" / "newdir"
    done = _run(tmp_path, dest, {env_name: str(live)} if env_name else {})
    assert done.returncode == 1 and "destination_inside_home" in done.stderr, done.stderr
    assert not dest.exists()


def test_extract_outside_every_home_still_works(tmp_path: Path) -> None:
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    dest = tmp_path / "elsewhere"
    done = _run(tmp_path, dest, {})
    assert done.returncode == 0 and (dest / "projects").is_dir(), done.stderr
