
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_JS_TEST = Path(__file__).resolve().parent / "test_dashboard_polls_gate.node.mjs"


@pytest.mark.skipif(
    subprocess.run(
        ["node", "--version"], capture_output=True, check=False
    ).returncode
    != 0,
    reason="node is not available in this environment",
)
def test_the_terminal_screen_keeps_the_polled_reads_running() -> None:
    result = subprocess.run(
        ["node", str(_JS_TEST)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "the dashboard poll gate has broken:\n"
        f"{result.stdout}\n{result.stderr}"
    )
