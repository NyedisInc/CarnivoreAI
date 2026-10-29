
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent

_NODE_OK = subprocess.run(
    ["node", "--version"], capture_output=True, check=False
).returncode == 0


@pytest.mark.skipif(not _NODE_OK, reason="node is not available in this environment")
@pytest.mark.parametrize(
    "name",
    ["test_session_sleep_client.node.mjs"],
)
def test_the_client_sleep_and_wake_specs_pass(name: str) -> None:
    result = subprocess.run(
        ["node", str(_HERE / name)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"{name} failed:\n{result.stdout}\n{result.stderr}"
    assert " passed, 0 failed" in result.stdout, (
        f"{name} reported no passing count, so it may have run nothing:\n{result.stdout}"
    )
