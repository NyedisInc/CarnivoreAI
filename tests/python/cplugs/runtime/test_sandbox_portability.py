
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.cplugs.runtime import sandbox

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="the sandbox is macOS only")


def framework(root: Path, minor: int, name: str = "Python.framework") -> Path:
    version = root / name / "Versions" / f"3.{minor}"
    app = version / "Resources" / "Python.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    (app / "Python").write_text("")
    return version


def bare_install(root: Path) -> Path:
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "python3").write_text("")
    (root / "lib" / "python3.12").mkdir(parents=True)
    return root


def test_homebrew_base_prefix_resolves(tmp_path: Path) -> None:
    version = framework(tmp_path / "opt/homebrew/Frameworks", 12)
    found = sandbox.find_interpreter(prefix=str(version), roots=())
    assert found == Path(os.path.realpath(version)) / "Resources/Python.app/Contents/MacOS/Python"


def test_apple_clt_base_prefix_resolves(tmp_path: Path) -> None:
    version = framework(tmp_path / "Library/Developer/CommandLineTools/Library/Frameworks", 9, name="Python3.framework")
    assert sandbox.find_interpreter(prefix=str(version), roots=()).is_file()


def test_python_org_found_from_a_venv_prefix_and_newest_wins(tmp_path: Path) -> None:
    roots = tmp_path / "Library/Frameworks"
    framework(roots, 12)
    newest = framework(roots, 13)
    framework(roots, 11)
    found = sandbox.find_interpreter(prefix=str(bare_install(tmp_path / "venv")), roots=(str(roots),))
    assert found == Path(os.path.realpath(newest)) / "Resources/Python.app/Contents/MacOS/Python"


def test_framework_below_the_app_minimum_is_ignored(tmp_path: Path) -> None:
    roots = tmp_path / "Library/Frameworks"
    framework(roots, sandbox.MIN_PYTHON_MINOR - 1)
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.find_interpreter(prefix=str(bare_install(tmp_path / "venv")), roots=(str(roots),))


@pytest.mark.parametrize("owner", ["pyenv", "uv"])
def test_pyenv_and_uv_have_no_framework_and_refuse(tmp_path: Path, owner: str) -> None:
    prefix = bare_install(tmp_path / ("pyenv/versions/3.12.7" if owner == "pyenv" else "uv/cpython-3.12.7-macos-aarch64"))
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.find_interpreter(prefix=str(prefix), roots=(str(tmp_path / "empty"),))


def test_probe_reports_unavailable_without_raising(tmp_path: Path) -> None:
    result = sandbox.probe(tmp_path / "no-such-python")
    assert not result.ok and not result.ran


def test_live_probe_refuses_the_denied_write_and_allows_files() -> None:
    try:
        sandbox.find_interpreter()
    except sandbox.SandboxUnavailable:
        pytest.skip("this machine has no framework Python")
    result = sandbox.probe()
    assert result.ran, result.detail
    assert result.denied_write_refused and result.allowed_write_ok, result
