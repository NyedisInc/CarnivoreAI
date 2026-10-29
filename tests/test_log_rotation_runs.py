
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_JS_TEST = Path(__file__).resolve().parent / "test_log_rotation.node.mjs"


@pytest.mark.skipif(
    subprocess.run(
        ["node", "--version"], capture_output=True, check=False
    ).returncode
    != 0,
    reason="node is not available in this environment",
)
def test_server_log_rotates_and_never_loses_a_line() -> None:
    result = subprocess.run(
        ["node", str(_JS_TEST)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "server.log rotation has broken:\n"
        f"{result.stdout}\n{result.stderr}"
    )
