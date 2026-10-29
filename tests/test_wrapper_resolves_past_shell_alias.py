from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wrap_alias_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wrap_alias_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.agent_wrappers import EXAMPLE_WRAPPER_CLDOR

MODERN_RESOLVE = (
    'claude_bin="$(unalias claude 2>/dev/null;'
    ' unset -f claude 2>/dev/null; command -v claude)"'
)

LEGACY_RESOLVE = 'claude_bin="$(command -v claude)"'

STUB_MARKER = "CLAUDE_INVOKED_WITH:"


def _shell_or_skip(name: str) -> str:
    found = shutil.which(name)
    if not found:
        pytest.skip(
            f"COULD NOT EVALUATE: {name} is not installed on this machine, so the "
            f"shell-alias resolution behaviour cannot be measured here. This is not "
            f"a pass."
        )
    return found


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_body_with_shadow(
    tmp_path: Path,
    case: str,
    shell: str,
    body: str,
    shadow: str,
) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / case
    bin_dir.mkdir()
    _write_executable(bin_dir / "security", "#!/bin/sh\necho fake-openrouter-key\nexit 0\n")
    _write_executable(
        bin_dir / "claude",
        f'#!/bin/sh\necho {STUB_MARKER}"$@"\nexit 0\n',
    )

    script = tmp_path / f"{case}_body.sh"
    script.write_text(body)

    stub = bin_dir / "claude"
    if shadow == "alias":
        shadow_stmt = f"alias claude='security unlock-keychain /dev/null && {stub}'"
    elif shadow == "function":
        shadow_stmt = f'claude() {{ "{stub}" "$@"; }}'
    elif shadow == "none":
        shadow_stmt = ":"
    else:
        raise ValueError(f"unknown shadow mode: {shadow}")

    prelude = "shopt -s expand_aliases 2>/dev/null || true"

    epilogue = 'printf "PARENT_ALIAS=[%s]\\n" "$(alias claude 2>/dev/null)"'

    program = (
        f"{prelude}\n{shadow_stmt}\n"
        f'source "{script}"\n'
        f'cldor "$@"\n'
        f"rc=$?\n{epilogue}\nexit $rc\n"
    )
    cmd = [shell, "-c", program, "_"]
    env = {"PATH": str(bin_dir), "HOME": str(tmp_path), "USER": "testuser"}
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)


def _legacy_body() -> str:
    assert EXAMPLE_WRAPPER_CLDOR.count(MODERN_RESOLVE) == 1, (
        "the shipped resolution expression was not found verbatim, so the "
        "non-vacuity control below would silently test the SAME body twice "
        "and prove nothing. Update MODERN_RESOLVE to match the body."
    )
    return EXAMPLE_WRAPPER_CLDOR.replace(MODERN_RESOLVE, LEGACY_RESOLVE)



def test_body_does_not_resolve_via_a_bare_command_v():
    assert LEGACY_RESOLVE not in EXAMPLE_WRAPPER_CLDOR
    assert MODERN_RESOLVE in EXAMPLE_WRAPPER_CLDOR


def test_body_rejects_a_non_executable_resolution_result():
    assert '[[ ! -x "$claude_bin" ]]' in EXAMPLE_WRAPPER_CLDOR



@pytest.mark.parametrize("shell_name", ["zsh", "bash"])
def test_resolves_past_an_alias_shadow(tmp_path, shell_name):
    shell = _shell_or_skip(shell_name)
    r = _run_body_with_shadow(
        tmp_path, f"alias_{shell_name}", shell, EXAMPLE_WRAPPER_CLDOR, "alias"
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert STUB_MARKER in r.stdout
    assert "--dangerously-skip-permissions" in r.stdout


@pytest.mark.parametrize("shell_name", ["zsh", "bash"])
def test_resolves_past_a_function_shadow(tmp_path, shell_name):
    shell = _shell_or_skip(shell_name)
    r = _run_body_with_shadow(
        tmp_path, f"func_{shell_name}", shell, EXAMPLE_WRAPPER_CLDOR, "function"
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert STUB_MARKER in r.stdout


@pytest.mark.parametrize("shell_name", ["zsh", "bash"])
def test_still_resolves_with_no_shadow_at_all(tmp_path, shell_name):
    shell = _shell_or_skip(shell_name)
    r = _run_body_with_shadow(
        tmp_path, f"none_{shell_name}", shell, EXAMPLE_WRAPPER_CLDOR, "none"
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert STUB_MARKER in r.stdout


@pytest.mark.parametrize("shell_name", ["zsh", "bash"])
def test_callers_alias_survives_the_wrapper(tmp_path, shell_name):
    shell = _shell_or_skip(shell_name)
    r = _run_body_with_shadow(
        tmp_path, f"survive_{shell_name}", shell, EXAMPLE_WRAPPER_CLDOR, "alias"
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    line = next(
        (ln for ln in r.stdout.splitlines() if ln.startswith("PARENT_ALIAS=[")),
        None,
    )
    assert line is not None, f"harness did not report PARENT_ALIAS: {r.stdout!r}"
    assert "claude='" in line, (
        f"the caller's alias did not survive the wrapper: {line!r}"
    )



@pytest.mark.parametrize("shell_name", ["zsh", "bash"])
def test_legacy_resolution_fails_under_the_same_harness(tmp_path, shell_name):
    shell = _shell_or_skip(shell_name)
    r = _run_body_with_shadow(
        tmp_path, f"legacy_{shell_name}", shell, _legacy_body(), "alias"
    )
    assert r.returncode != 0, (
        "the legacy `command -v claude` form SUCCEEDED under an alias shadow. "
        "The harness is not reproducing the defect, so none of the passing "
        f"tests in this file are evidence. stdout={r.stdout!r}"
    )
    assert STUB_MARKER not in r.stdout
    assert "claude not found on path" in (r.stdout + r.stderr).lower()


@pytest.mark.parametrize("shell_name", ["zsh", "bash"])
def test_legacy_resolution_still_passes_without_a_shadow(tmp_path, shell_name):
    shell = _shell_or_skip(shell_name)
    r = _run_body_with_shadow(
        tmp_path, f"legacyok_{shell_name}", shell, _legacy_body(), "none"
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert STUB_MARKER in r.stdout
