
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_JS_TEST = Path(__file__).resolve().parent / "test_extend_prototype.node.mjs"


@pytest.mark.skipif(
    subprocess.run(["node", "--version"], capture_output=True, check=False).returncode != 0,
    reason="node is not available in this environment",
)
def test_a_prototype_patch_that_collides_keeps_the_first_and_strict_mode_throws() -> None:
    result = subprocess.run(["node", str(_JS_TEST)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"node suite failed:\n{result.stdout}\n{result.stderr}"
    assert "5/5 passed" in result.stdout
