
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFIER = REPO_ROOT / "scripts" / "verify_login_chrome.py"

CANDIDATE_INTERPRETERS = (
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "python3",
)


def _playwright_interpreter() -> str | None:
    probe = (
        "import sys\n"
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    b = p.chromium.launch(args=['--use-mock-keychain'])\n"
        "    b.close()\n"
    )
    for candidate in CANDIDATE_INTERPRETERS:
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if not resolved or not Path(resolved).exists():
            continue
        try:
            done = subprocess.run(
                [resolved, "-c", probe],
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return resolved
    return None


def test_legacy_control_reproduces_the_reported_bug() -> None:
    interpreter = _playwright_interpreter()
    if interpreter is None:
        pytest.skip(
            "no interpreter with playwright and a working chromium was found, "
            "so whether the login-chrome control can still fail was NOT "
            "measured. This is a could-not-evaluate, not a pass."
        )

    done = subprocess.run(
        [interpreter, str(VERIFIER), "--legacy"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(REPO_ROOT),
    )

    if done.returncode == 2:
        pytest.skip(
            "the control reported CANNOT DETERMINE, so it was not measured: "
            + (done.stderr or done.stdout)[-600:]
        )

    assert done.returncode == 0, (
        "scripts/verify_login_chrome.py --legacy did not reproduce the "
        "pre-fix bug, so the verifier's positive control cannot fail and "
        "proves nothing. stdout/stderr follows:\n"
        + (done.stdout or "")[-1500:]
        + (done.stderr or "")[-1500:]
    )
    assert "CONTROL OK" in done.stdout, (
        "exit 0 without a CONTROL OK verdict - the control's own reporting "
        "has drifted from its exit code."
    )
