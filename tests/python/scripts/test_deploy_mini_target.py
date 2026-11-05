from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deploy-mini.sh"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=30)


def test_bare_run_refuses_without_a_target() -> None:
    r = _run("--dry-run")
    assert r.returncode == 64
    assert "--target live" in r.stderr


def test_retired_v11_target_is_unknown() -> None:
    r = _run("--target", "v11", "--dry-run")
    assert r.returncode == 64
    assert "unknown target" in r.stderr
