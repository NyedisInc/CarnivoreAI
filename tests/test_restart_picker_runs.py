
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_JS_TEST = Path(__file__).resolve().parent / "test_restart_picker.node.mjs"


@pytest.mark.skipif(
    subprocess.run(
        ["node", "--version"], capture_output=True, check=False
    ).returncode
    != 0,
    reason="node is not available in this environment",
)
def test_the_restart_picker_predicts_without_permitting() -> None:
    result = subprocess.run(
        ["node", str(_JS_TEST)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "the restart picker's prediction/permission split has broken:\n"
        f"{result.stdout}\n{result.stderr}"
    )
