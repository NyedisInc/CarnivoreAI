
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "js_syntax_check.py"

BROKEN_MODULE = "export const a = 1;\nfunction broken( {\n"
BROKEN_SCRIPT = "var a = 1;\nfunction broken( {\n"
VALID_MODULE = "export const a = 1;\nexport function ok() { return a; }\n"
VALID_SCRIPT = "var a = 1;\nfunction ok() { return a; }\n"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed"
)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_it_fails_on_a_broken_module_and_a_broken_script(tmp_path: Path) -> None:
    (tmp_path / "mod.js").write_text(BROKEN_MODULE, encoding="utf-8")
    (tmp_path / "plain.js").write_text(BROKEN_SCRIPT, encoding="utf-8")

    result = run_script(str(tmp_path))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "mod.js" in result.stdout, result.stdout
    assert "plain.js" in result.stdout, result.stdout
    assert "checked 1 modules, 1 scripts" in result.stdout, result.stdout


def test_it_passes_on_valid_files_of_both_kinds(tmp_path: Path) -> None:
    (tmp_path / "mod.js").write_text(VALID_MODULE, encoding="utf-8")
    (tmp_path / "plain.js").write_text(VALID_SCRIPT, encoding="utf-8")

    result = run_script(str(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "checked 1 modules, 1 scripts" in result.stdout, result.stdout


def test_an_empty_directory_is_could_not_check_not_a_pass(tmp_path: Path) -> None:
    result = run_script(str(tmp_path))

    assert result.returncode == 2, result.stdout + result.stderr
    assert result.returncode != 0


def test_plain_node_check_is_blind_to_the_broken_module(tmp_path: Path) -> None:
    broken = tmp_path / "mod.js"
    broken.write_text(BROKEN_MODULE, encoding="utf-8")

    result = run_script(str(broken))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "mod.js" in result.stdout, result.stdout

    blind = subprocess.run(
        ["node", "--check", str(broken)], capture_output=True, text=True
    )
    if "SyntaxError" in blind.stderr:
        pytest.skip("this Node reports the broken module itself; no blind spot to pin")
    assert blind.stderr.strip() == "", blind.stderr


@pytest.mark.parametrize("pruned", ["node_modules", "node_modules.nosync", "vendor"])
def test_third_party_trees_are_pruned_from_a_directory_scan(tmp_path: Path, pruned: str) -> None:
    (tmp_path / pruned / "pkg").mkdir(parents=True)
    (tmp_path / pruned / "pkg" / "bad.js").write_text(BROKEN_SCRIPT, encoding="utf-8")
    (tmp_path / "ok.js").write_text(VALID_SCRIPT, encoding="utf-8")

    result = run_script(str(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
