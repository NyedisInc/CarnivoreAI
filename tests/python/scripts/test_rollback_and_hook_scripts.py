
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROLLBACK = ROOT / "scripts" / "rollback.sh"
INSTALLER = ROOT / "scripts" / "install-secret-hook.sh"


def _function(name: str) -> str:
    lines = ROLLBACK.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(f"{name}() {{"))
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _run_trap(tmp_path: Path, exit_code: int, server_stopped: int) -> str:
    log = tmp_path / "log.txt"
    body = f"""
trail_code_close() {{ echo "closed status=$6 err=$8" >> {str(log)!r}; }}
log_unknown() {{ echo "unknown: $*" >> {str(log)!r}; }}
INSTALL_DIR=/i; TRAIL_UUID=u; TRAIL_STARTED=s; CURRENT=c; TARGET_TAG=t; TRAIL_OPENED=1
ROLLBACK_STEP="installing dependencies"; SERVER_STOPPED={server_stopped}
{_function("close_trail")}
{_function("on_rollback_exit")}
trap on_rollback_exit EXIT
exit {exit_code}
"""
    subprocess.run(["bash", "-c", body], cwd=tmp_path, timeout=30)
    return log.read_text() if log.exists() else ""


def test_a_failure_after_the_trail_opened_closes_it_and_names_the_step(tmp_path: Path) -> None:
    text = _run_trap(tmp_path, exit_code=1, server_stopped=1)
    assert "closed status=failed err=stopped at step: installing dependencies" in text
    assert "server is STOPPED" in text


def test_a_clean_exit_closes_nothing(tmp_path: Path) -> None:
    assert _run_trap(tmp_path, exit_code=0, server_stopped=1) == ""


def test_the_trail_entry_is_never_closed_twice(tmp_path: Path) -> None:
    log = tmp_path / "log.txt"
    body = f"""
trail_code_close() {{ echo closed >> {str(log)!r}; }}
INSTALL_DIR=/i; TRAIL_UUID=u; TRAIL_STARTED=s; CURRENT=c; TARGET_TAG=t; TRAIL_OPENED=1
{_function("close_trail")}
close_trail failed x; close_trail failed y
"""
    subprocess.run(["bash", "-c", body], cwd=tmp_path, timeout=30)
    assert log.read_text().count("closed") == 1


def test_the_script_installs_the_trap_after_the_trail_opens() -> None:
    source = ROLLBACK.read_text()
    assert source.index("trap on_rollback_exit EXIT") > source.index("trail_code_open")
    assert "this may still work, but proceed with caution" not in source


def test_the_installed_hook_follows_the_checkout_it_runs_in(tmp_path: Path) -> None:
    repo = tmp_path / "repo with space"
    (repo / "scripts" / "hooks").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    hook_src = repo / "scripts" / "hooks" / "pre-commit-secret-scan.sh"
    hook_src.write_text("#!/bin/sh\necho scanned-by-this-checkout\n")
    hook_src.chmod(0o755)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
    shutil_copy = (repo / "scripts" / "install-secret-hook.sh")
    shutil_copy.write_text(INSTALLER.read_text())
    shutil_copy.chmod(0o755)
    subprocess.run(["sh", str(shutil_copy)], cwd=repo, check=True, capture_output=True, env=env)
    installed = repo / ".git" / "hooks" / "pre-commit"
    assert str(repo) not in installed.read_text()
    ok = subprocess.run([str(installed)], cwd=repo, capture_output=True, text=True, env=env)
    assert "scanned-by-this-checkout" in ok.stdout
    hook_src.unlink()
    gone = subprocess.run([str(installed)], cwd=repo, capture_output=True, text=True, env=env)
    assert gone.returncode != 0 and "secret scan hook missing" in gone.stderr
