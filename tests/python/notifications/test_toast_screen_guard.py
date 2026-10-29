
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_JS_TEST = Path(__file__).resolve().parent / "test_toast_screen_guard.node.mjs"


@pytest.mark.skipif(
    subprocess.run(["node", "--version"], capture_output=True, check=False).returncode != 0,
    reason="node is not available in this environment",
)
def test_the_toast_guard_hides_an_unticked_type_and_fails_open_without_the_module() -> None:
    result = subprocess.run(["node", str(_JS_TEST)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"node suite failed:\n{result.stdout}\n{result.stderr}"
    assert "3/3 passed" in result.stdout
