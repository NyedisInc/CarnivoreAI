
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "work"

STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
case "$1" in
  api) echo maintainer; exit 0 ;;
  issue)
    case "$*" in
      *"--state open"*) echo '[{"number":7,"title":"answered open","state":"OPEN","comments":[{"author":{"login":"maintainer"}}]}]' ;;
      *"closed:>="*) echo '[{"number":2953,"title":"owed closed","state":"CLOSED","comments":[{"author":{"login":"joe"}}]}]' ;;
    esac
    exit 0 ;;
  pr) echo '[]'; exit 0 ;;
esac
exit 1
"""


def _env(tmp_path: Path) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    return {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "GH_TOKEN": "stub-not-a-token",
        "STUB_LOG": str(tmp_path / "gh.log"),
        "WORK_SWEEP_CACHE_DIR": str(tmp_path / "cache"),
    }


def _run(script: str, env: dict[str, str], *args: str) -> str:
    r = subprocess.run(
        ["bash", str(SKILL / script), *args],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_unanswered_lists_owed_closed_and_skips_answered_open(tmp_path: Path) -> None:
    env = _env(tmp_path)
    out = _run("work.sh", env, "unanswered")
    assert "#2953 [closed]" in out and "owed closed" in out
    assert "answered open" not in out
    assert "closed:>=" in (tmp_path / "gh.log").read_text()


def test_hook_prints_block_and_reuses_cache_within_an_hour(tmp_path: Path) -> None:
    env = _env(tmp_path)
    first = _run("session-start-unanswered.sh", env)
    assert "github threads waiting on maintainer:" in first
    assert "#2953 owed closed (CarnivoreAIDev, closed)" in first
    assert "answered open" not in first
    log = tmp_path / "gh.log"
    calls = len(log.read_text().splitlines())
    second = _run("session-start-unanswered.sh", env)
    assert second == first
    assert len(log.read_text().splitlines()) == calls
