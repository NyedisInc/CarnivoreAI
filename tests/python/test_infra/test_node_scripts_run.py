
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

NODE_TIMEOUT_S = 120

_NODE_OK = subprocess.run(["node", "--version"], capture_output=True, check=False).returncode == 0

SCRIPTS = sorted((REPO / "tests").rglob("*.node.mjs"))


def run_node_script(script: Path, timeout_s: float = NODE_TIMEOUT_S) -> tuple[int, str]:
    try:
        done = subprocess.run(
            ["node", str(script)], cwd=REPO, capture_output=True, text=True,
            timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired as err:
        out = (err.stdout or b"")
        text = out.decode(errors="replace") if isinstance(out, bytes) else out
        return -1, f"timed out after {timeout_s} s\n{text[-600:]}"
    return done.returncode, (done.stdout + done.stderr)[-1500:]


@pytest.mark.skipif(not _NODE_OK, reason="node is not available in this environment")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_node_script_passes_and_exits(script: Path) -> None:
    code, tail = run_node_script(script)
    assert code == 0, f"{script.name} exited {code}:\n{tail}"


def test_the_scripts_were_found() -> None:
    assert len(SCRIPTS) > 100, f"only {len(SCRIPTS)} node scripts found under tests/"


@pytest.mark.skipif(not _NODE_OK, reason="node is not available in this environment")
def test_a_hanging_script_is_reported_as_a_failure(tmp_path: Path) -> None:
    hang = tmp_path / "hang.node.mjs"
    hang.write_text("console.log('ALL PASS'); setInterval(() => {}, 1000);\n")
    code, tail = run_node_script(hang, timeout_s=2)
    assert code == -1 and "timed out" in tail


@pytest.mark.skipif(not _NODE_OK, reason="node is not available in this environment")
def test_a_failing_script_is_reported_as_a_failure(tmp_path: Path) -> None:
    bad = tmp_path / "bad.node.mjs"
    bad.write_text("process.exit(1);\n")
    assert run_node_script(bad, timeout_s=10)[0] == 1
