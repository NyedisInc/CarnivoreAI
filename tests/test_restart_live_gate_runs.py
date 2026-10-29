
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_JS_TEST = Path(__file__).resolve().parent / "test_restart_live_gate.node.mjs"


@pytest.mark.skipif(
    subprocess.run(
        ["node", "--version"], capture_output=True, check=False
    ).returncode
    != 0,
    reason="node is not available in this environment",
)
def test_a_live_restart_needs_three_deliberate_gates() -> None:
    result = subprocess.run(
        ["node", str(_JS_TEST)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "a gate on restarting a live session has broken:\n"
        f"{result.stdout}\n{result.stderr}"
    )
