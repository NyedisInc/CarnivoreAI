from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wrap_path_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wrap_path_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.agent_wrappers import EXAMPLE_WRAPPER_CLD, EXAMPLE_WRAPPER_CLDOR

_BASH = shutil.which("bash") or "/bin/bash"

_HARDCODED_HOME_PATH_AS_COMMAND = re.compile(r'^"(\$HOME|~)/\S+"\s*\\?$')


def _lines_that_hardcode_a_home_path_as_a_command(body: str) -> list:
    return [
        line.strip()
        for line in body.splitlines()
        if _HARDCODED_HOME_PATH_AS_COMMAND.match(line.strip())
    ]


def test_example_wrapper_cld_has_no_hardcoded_home_path_command():
    assert _lines_that_hardcode_a_home_path_as_a_command(EXAMPLE_WRAPPER_CLD) == []


def test_example_wrapper_cldor_has_no_hardcoded_home_path_command():
    assert _lines_that_hardcode_a_home_path_as_a_command(EXAMPLE_WRAPPER_CLDOR) == []


def test_regression_guard_is_not_vacuous_against_the_shipped_defect():
    original_defective_line = '"$HOME/.local/bin/claude" \\'
    assert _HARDCODED_HOME_PATH_AS_COMMAND.match(original_defective_line.strip())


def test_cldor_resolves_claude_via_path_lookup_not_a_literal_path():
    assert "command -v claude" in EXAMPLE_WRAPPER_CLDOR
    assert '"$HOME/.local/bin/claude"' not in EXAMPLE_WRAPPER_CLDOR
    invocation_sites = [
        line.strip()
        for line in EXAMPLE_WRAPPER_CLDOR.splitlines()
        if line.strip().startswith('"$claude_bin"')
    ]
    assert len(invocation_sites) == 2, invocation_sites



def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_cldor(tmp_path: Path, bin_dir_name: str, claude_present: bool, args: list):
    bin_dir = tmp_path / bin_dir_name
    bin_dir.mkdir()
    _write_executable(bin_dir / "security", "#!/bin/bash\necho fake-openrouter-key\nexit 0\n")
    if claude_present:
        _write_executable(
            bin_dir / "claude",
            '#!/bin/bash\necho CLAUDE_INVOKED_WITH:"$@"\nexit 0\n',
        )
    script = tmp_path / f"{bin_dir_name}_cldor_body.sh"
    script.write_text(EXAMPLE_WRAPPER_CLDOR)
    cmd = [_BASH, "-c", f'source {script} ; cldor "$@"', "_"] + args
    env = {"PATH": str(bin_dir), "HOME": str(tmp_path), "USER": "testuser"}
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)


def test_cldor_invokes_the_claude_found_on_path(tmp_path):
    result = _run_cldor(tmp_path, "bin_present", claude_present=True, args=["vendor/some-model"])
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "CLAUDE_INVOKED_WITH:" in result.stdout
    assert "--dangerously-skip-permissions" in result.stdout
    assert "--model" in result.stdout
    assert "vendor/some-model" in result.stdout


def test_cldor_invokes_the_claude_found_on_path_default_branch_no_model(tmp_path):
    result = _run_cldor(tmp_path, "bin_present_default", claude_present=True, args=[])
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "CLAUDE_INVOKED_WITH:" in result.stdout
    assert "--dangerously-skip-permissions" in result.stdout
    assert "--model" not in result.stdout


def test_cldor_missing_claude_fails_with_named_message_not_raw_shell_error(tmp_path):
    result = _run_cldor(tmp_path, "bin_absent", claude_present=False, args=[])
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "claude not found on path" in combined
    assert "no such file or directory" not in combined
