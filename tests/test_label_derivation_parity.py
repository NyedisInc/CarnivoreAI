
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.core.session_label import label_from_tmux_name

_CASES_PATH = Path(__file__).resolve().parent / "label_derivation_cases.json"
_JS_PARITY_TEST = Path(__file__).resolve().parent / "test_label_derivation_parity.node.mjs"


def _load_cases() -> list[dict]:
    payload = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert cases, "the shared derivation table is empty - nothing pinned"
    return cases


@pytest.mark.parametrize(
    "case", _load_cases(), ids=lambda c: c["tmux_name"]
)
def test_label_from_tmux_name_matches_the_shared_table(case: dict) -> None:
    assert label_from_tmux_name(case["tmux_name"]) == case["expected"]


def test_the_shared_table_is_not_accidentally_trivial() -> None:
    assert any("_" in c["tmux_name"].split("cloude_", 1)[-1] for c in _load_cases())


@pytest.mark.skipif(
    subprocess.run(
        ["node", "--version"], capture_output=True, check=False
    ).returncode
    != 0,
    reason="node is not available in this environment",
)
def test_the_js_side_agrees_with_the_same_table() -> None:
    result = subprocess.run(
        ["node", str(_JS_PARITY_TEST)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"JS label-derivation parity test failed:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
