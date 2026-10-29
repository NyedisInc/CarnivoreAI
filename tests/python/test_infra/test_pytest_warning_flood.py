
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

SUBJECT = "tests/test_docs_index.py"

_FLOOD_LINE = re.compile(r"pytest_asyncio/plugin\.py:\d+: (\d+) warnings?")
_COLLECTED = re.compile(r"(\d+) tests? collected")


def _collect(*extra: str) -> tuple[int, int, str]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:xdist",
            *extra,
            SUBJECT,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    collected = _COLLECTED.search(out)
    assert collected, f"no 'tests collected' line, so nothing was measured:\n{out}"
    flood = sum(int(m) for m in _FLOOD_LINE.findall(out))
    return int(collected.group(1)), flood, out


def test_the_repository_config_records_no_pytest_asyncio_deprecations() -> None:
    collected, flood, out = _collect()
    assert collected > 0, out
    assert flood == 0, (
        f"{flood} pytest-asyncio DeprecationWarning records while collecting "
        f"{collected} test(s); the pytest.ini filter for issue #1056 is gone "
        f"or no longer matches:\n{out}"
    )


@pytest.mark.skipif(
    sys.version_info < (3, 14),
    reason=(
        "asyncio.iscoroutinefunction is only deprecated from Python 3.14, so "
        "on an older interpreter the flood cannot occur and the control has "
        "nothing to measure (the venv here is 3.12)"
    ),
)
def test_without_the_filter_the_flood_is_really_there() -> None:
    collected, flood, out = _collect("-o", "filterwarnings=")
    assert collected > 0, out
    assert flood >= collected, (
        "pytest-asyncio no longer raises the asyncio.iscoroutinefunction "
        "deprecation during collection. If it was upgraded past the call, "
        "remove the issue #1056 filter from pytest.ini and this file:\n" + out
    )
