from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _collected_node_ids(marker_expr: str, target: str) -> set[str]:
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
            "--collect-only", "-m", marker_expr, target,
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        line.strip()
        for line in proc.stdout.splitlines()
        if "::" in line
    }


def test_recreate_gate_real_tmux_carries_the_marker():
    ids = _collected_node_ids(
        "real_tmux", "tests/test_recreate_gate_real_tmux.py"
    )
    assert ids, (
        "test_recreate_gate_real_tmux.py should carry the real_tmux "
        "marker - it drives a real tmux server via derive_test_socket"
    )


def test_a_known_fast_test_does_not_carry_the_marker():
    ids = _collected_node_ids("real_tmux", "tests/test_project_theme.py")
    assert ids == set(), (
        "test_project_theme.py drives no real tmux and must not carry "
        f"the real_tmux marker; got: {ids}"
    )
