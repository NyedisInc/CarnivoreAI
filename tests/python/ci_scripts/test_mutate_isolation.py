
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
VENV = REPO / "venv"

SCRIPT = """#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/scripts/ci/lib/mutate-trap.sh"
echo "ran in $ROOT"
echo mutant > "$ROOT/target.txt"
exit 0
"""


@pytest.fixture()
def scratch_repo(tmp_path: Path) -> Path:
    if not VENV.exists():
        pytest.skip("no venv to link into the copy")
    root = tmp_path / "repo"
    for rel in ("scripts/ci/lib/mutate-trap.sh", "scripts/ci/lib/isolate_tree.py", "scripts/gate/tree_copy.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)
    (root / "scripts/ci/mutate-demo.sh").write_text(SCRIPT)
    (root / "scripts/ci/mutate-demo.sh").chmod(0o755)
    (root / "target.txt").write_text("original\n")
    (root / "venv").symlink_to(VENV.resolve())
    for cmd in (["init", "-q"], ["add", "-A", "-f"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(["git", *cmd], cwd=root, check=True, capture_output=True)
    return root


def _run(root: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(root / "scripts/ci/mutate-demo.sh")], cwd=root, capture_output=True, text=True, timeout=120,
                          env={**os.environ, **env})


def test_the_live_checkout_is_never_mutated(scratch_repo: Path) -> None:
    done = _run(scratch_repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (scratch_repo / "target.txt").read_text() == "original\n"
    assert f"ran in {scratch_repo}" not in done.stdout
    assert "ran in " in done.stdout


def test_in_place_is_the_only_way_to_edit_the_live_tree(scratch_repo: Path) -> None:
    done = _run(scratch_repo, MUTATE_IN_PLACE="1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (scratch_repo / "target.txt").read_text() == "mutant\n"


def test_a_failed_copy_is_could_not_run_not_a_pass(scratch_repo: Path) -> None:
    (scratch_repo / "scripts/ci/lib/isolate_tree.py").write_text("raise SystemExit(7)\n")
    done = _run(scratch_repo)
    assert done.returncode == 2, done.stdout + done.stderr
    assert (scratch_repo / "target.txt").read_text() == "original\n"


MUTANT_SCRIPT = """#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$ROOT/scripts/ci/lib/mutate-trap.sh"
mutate_arm_trap "$ROOT" target.txt
{baseline}
echo mutant > "$ROOT/target.txt"
mutate_run bash -c 'exit {code}'
echo "scored status $?"
exit 0
"""


def _mutant(root: Path, code: int, baseline: str = "") -> subprocess.CompletedProcess:
    script = root / "scripts/ci/mutate-demo.sh"
    script.write_text(MUTANT_SCRIPT.replace("{code}", str(code)).replace("{baseline}", baseline))
    return _run(root, MUTATE_IN_PLACE="1")


def test_a_failing_suite_is_a_kill(scratch_repo: Path) -> None:
    done = _mutant(scratch_repo, 1)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "scored status 1" in done.stdout
    assert (scratch_repo / "target.txt").read_text() == "original\n"


@pytest.mark.parametrize("code", [2, 3, 5, 127])
def test_a_crashed_suite_is_could_not_evaluate_never_a_kill(scratch_repo: Path, code: int) -> None:
    done = _mutant(scratch_repo, code)
    assert done.returncode == 2, done.stdout + done.stderr
    assert "CANNOT_DETERMINE" in done.stdout + done.stderr
    assert (scratch_repo / "target.txt").read_text() == "original\n"


def test_a_red_baseline_refuses_to_run(scratch_repo: Path) -> None:
    done = _mutant(scratch_repo, 1, baseline="mutate_baseline bash -c 'exit 1'")
    assert done.returncode == 2, done.stdout + done.stderr
    assert "scored status" not in done.stdout
    assert "BASELINE IS RED" in done.stdout + done.stderr


def test_a_green_baseline_lets_the_run_go_on(scratch_repo: Path) -> None:
    done = _mutant(scratch_repo, 1, baseline="mutate_baseline bash -c 'exit 0'")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "scored status 1" in done.stdout


def test_every_mutation_script_gates_on_a_green_baseline() -> None:
    scripts = sorted((REPO / "scripts" / "ci").glob("mutate-*.sh"))
    assert scripts, "no mutation scripts found"
    def gated(text: str) -> bool:
        return "baseline" in text.lower() or "CANNOT DETERMINE" in text

    ungated = [p.name for p in scripts if not gated(p.read_text())]
    assert ungated == [], f"mutation scripts with no baseline gate: {ungated}"
