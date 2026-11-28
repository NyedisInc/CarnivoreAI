
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path.home() / ".handoff" / "handoff"
CASES = Path(__file__).with_name("handoff_wait_callback_cases.py")


@pytest.mark.skipif(not RUNNER.is_file() or "carnivore-wait" not in RUNNER.read_text(errors="replace"), reason="no handoff runner with the wait callback on this machine")
def test_the_handoff_runner_calls_the_wait_callback_with_the_token_in_the_body_only():
    done = subprocess.run([sys.executable, str(CASES), str(RUNNER)], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "Ran 8 tests" in done.stderr and "OK" in done.stderr
