
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent

_NODE_OK = subprocess.run(
    ["node", "--version"], capture_output=True, check=False
).returncode == 0


@pytest.mark.skipif(not _NODE_OK, reason="node is not available in this environment")
def test_the_drawer_keep_awake_cup_spec_passes() -> None:
    name = "test_session_sidebar_keep_awake.node.mjs"
    result = subprocess.run(
        ["node", str(_HERE / name)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"{name} failed:\n{result.stdout}\n{result.stderr}"
    assert " passed, 0 failed" in result.stdout, (
        f"{name} reported no passing count, so it may have run nothing:\n{result.stdout}"
    )
