
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import List

import pytest

from src.core.pack.jobs.ssh import far_script

SSH_DIR = Path(far_script.__file__).resolve().parent
SCRIPTS = ["driver.sh", "run.sh"]
BANNED = {
    "local": r"(^|[\s;{(])local\s",
    "[[": r"\[\[",
    "array": r"\b\w+=\(",
    "builtin kill with --": r"\bkill\s+--",
    "echo -e": r"\becho\s+-e\b",
    "readlink -f": r"\breadlink\s+-f\b",
    "bash source": r"(^|[\s;])source\s",
    "function keyword": r"(^|[\s;])function\s+\w",
    "here-string": r"<<<",
    "ansi-c quote": r"\$'",
    "&> redirect": r"&>",
    "|& pipe": r"\|&",
    "declare": r"\bdeclare\s",
}


def _hits(text: str) -> List[str]:
    return [name for name, pattern in BANNED.items() if re.search(pattern, text, re.M)]


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_was_read_and_is_not_empty(name: str) -> None:
    text = (SSH_DIR / name).read_text()
    assert len(text) > 1500 and ("cvj_main" in text or "finish()" in text)


@pytest.mark.parametrize("name", SCRIPTS)
def test_no_banned_construct(name: str) -> None:
    assert _hits((SSH_DIR / name).read_text()) == []


def test_lint_can_fail() -> None:
    bad = ["local x=1", "if [[ -n $a ]]; then", "a=(1 2)", "kill -- -123", "echo -e 'a'", "readlink -f x", "source f", "function f {", "cat <<< x"]
    assert all(_hits(sample) for sample in bad)
    assert _hits('"$KILLBIN" -s TERM -- "-$pg"') == []


@pytest.mark.parametrize("name", SCRIPTS)
def test_sh_syntax(name: str) -> None:
    assert subprocess.run(["/bin/sh", "-n", str(SSH_DIR / name)], capture_output=True).returncode == 0


@pytest.mark.skipif(shutil.which("dash") is None, reason="dash is not installed on this computer, so only sh -n ran")
@pytest.mark.parametrize("name", SCRIPTS)
def test_dash_syntax(name: str) -> None:
    assert subprocess.run([shutil.which("dash") or "dash", "-n", str(SSH_DIR / name)], capture_output=True).returncode == 0


def test_no_second_place_builds_a_driver_call() -> None:
    others = [p for p in SSH_DIR.glob("*.py") if p.name != "far_script.py"]
    assert all("CVJ_" not in p.read_text() for p in others)
