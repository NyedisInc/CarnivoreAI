
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_JS_TEST = Path(__file__).resolve().parent / "test_extend_prototype_page_order.node.mjs"


@pytest.mark.skipif(
    subprocess.run(["node", "--version"], capture_output=True, check=False).returncode != 0,
    reason="node is not available in this environment",
)
def test_no_api_file_redefines_a_method_in_page_order() -> None:
    result = subprocess.run(["node", str(_JS_TEST)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"node suite failed:\n{result.stdout}\n{result.stderr}"
    assert "1/1 passed" in result.stdout
