
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_REL = Path("scripts") / "ci" / "check-js-syntax.sh"
SCRIPT = REPO_ROOT / SCRIPT_REL
PY_TOOL_REL = Path("scripts") / "js_syntax_check.py"
PY_TOOL = REPO_ROOT / PY_TOOL_REL

DEBRIS = "__js_syntax_scan_coverage_test__.js"

UNCOVERED_UNTIL_2026_08_26 = [
    Path("client") / "css" / "themes" / "matrix",
    Path("client"),
]


def _run(root: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(root / SCRIPT_REL)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(root),
    )


def _scratch_repo(tmp_path: Path) -> Path:
    (tmp_path / SCRIPT_REL).parent.mkdir(parents=True)
    (tmp_path / SCRIPT_REL).write_bytes(SCRIPT.read_bytes())
    (tmp_path / PY_TOOL_REL).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / PY_TOOL_REL).write_bytes(PY_TOOL.read_bytes())
    for rel in [Path("macOS"), *UNCOVERED_UNTIL_2026_08_26]:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_clean_tree_parses_including_es_modules() -> None:
    done = _run()
    assert done.returncode == 0, (
        "the committed tree no longer parses:\n" + done.stderr[-2000:]
    )
    matched = re.search(r"checked (\d+) modules, (\d+) scripts", done.stdout)
    assert matched is not None, done.stdout
    assert int(matched.group(1)) > 0, (
        "no file was classified as an ES module, so the theme tree fell out of the scan or the "
        "classifier broke: " + done.stdout
    )


def test_es_module_source_does_not_false_fail(tmp_path: Path) -> None:
    root = _scratch_repo(tmp_path)
    planted = root / "client" / "css" / "themes" / "matrix" / DEBRIS
    planted.write_text("export const marker = 1;\nimport.meta.url;\n")
    done = _run(root)

    assert done.returncode == 0, (
        "valid ES module source was reported as a syntax error, which is "
        "exactly the false-fail the module goal exists to prevent. "
        "stdout: %s stderr: %s" % (done.stdout[-800:], done.stderr[-800:])
    )
    assert DEBRIS not in done.stdout + done.stderr, (
        "the planted ES module was named as broken: %s" % done.stderr[-800:]
    )
    assert "checked 1 modules, 0 scripts" in done.stdout, (
        "the scan did not reach the one planted file, so the clean exit "
        "proves nothing: %s" % done.stdout[-800:]
    )


@pytest.mark.parametrize("relative_dir", UNCOVERED_UNTIL_2026_08_26,
                         ids=lambda p: str(p).replace("/", "_"))
def test_scan_reaches_previously_unscanned_tree(relative_dir: Path,
                                                tmp_path: Path) -> None:
    root = _scratch_repo(tmp_path)
    planted = root / relative_dir / DEBRIS
    planted.write_text("function (){\n")
    done = _run(root)

    assert done.returncode == 1, (
        "a syntactically broken file in %s did not fail the checker, so that "
        "tree is outside the default scan. stdout: %s stderr: %s"
        % (relative_dir, done.stdout[-800:], done.stderr[-800:])
    )
    assert DEBRIS in done.stdout + done.stderr, (
        "the checker failed but never named the broken file in %s, so it may "
        "have failed for an unrelated reason: %s"
        % (relative_dir, done.stderr[-800:])
    )
