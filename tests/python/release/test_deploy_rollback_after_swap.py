
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.python.release import test_deploy_detached_engine as harness
from tests.python.release.test_deploy_restart_on_refusal import _block

OLD_VERSION = "1.0.0"
NEW_VERSION = "2.0.0"
FUNCS = ("log", "bootstrap_with_retries", "rollback_install", "restart_previous_app", "arm_rollback_if_swapped", "on_exit", "boot_out_all_carnivore_jobs")


def _write_app(contents: Path, version: str) -> None:
    contents.mkdir(parents=True)
    (contents / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>CFBundleShortVersionString</key>'
        f"<string>{version}</string></dict></plist>"
    )


def _installed_version(app: Path) -> str:
    out = subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Print CFBundleShortVersionString", str(app / "Contents/Info.plist")], capture_output=True, text=True)
    return out.stdout.strip()


def _run(tmp: Path, tail: str, mv_fails: bool = False, staged_version: str = NEW_VERSION) -> tuple[subprocess.CompletedProcess, list[str], Path]:
    text = harness.SCRIPT.read_text(encoding="utf-8")
    app, stage = tmp / "Carnivore.app", tmp / "stage"
    _write_app(app / "Contents", OLD_VERSION)
    _write_app(stage / "Carnivore.app" / "Contents", staged_version)
    calls = tmp / "calls.log"
    bindir = tmp / "bin"
    bindir.mkdir()
    stubs = {
        "launchctl": f'echo "launchctl $*" >> "{calls}"\n[ "$1" = print ] && exit 1\nexit 0\n',
        "open": f'echo "open $*" >> "{calls}"\n',
        "pgrep": "exit 1\n",
        "mv": 'echo "TEST STUB: mv refused" >&2\nexit 1\n' if mv_fails else 'exec /bin/mv "$@"\n',
    }
    for name, body in stubs.items():
        (bindir / name).write_text("#!/bin/bash\n" + body)
        (bindir / name).chmod(0o755)
    traps = "\n".join(line for line in text.splitlines() if line.startswith("trap "))
    funcs = "\n".join(_block(text, n) for n in FUNCS if f"\n{n}() {{" in text)
    script = (
        "set -euo pipefail\nTS=t\nPLIST=/nonexistent.plist\nLABEL=ai.test.label\n"
        f'CUR={OLD_VERSION}\nV={NEW_VERSION}\nAPP="{app}"\nSTAGE="{stage}"\nSTAGED_APP="{stage}/Carnivore.app"\nOLD="{tmp}/old"\n'
        f'SWAP_HELPER="{harness.SCRIPT.parent / "deploy" / "swap_dirs.py"}"\nROLLBACK_ARMED=0\nKEEP_STAGE=0\nOLD_CONTENTS=""\nMNT=""\nOLD_APP_STOPPED=0\nPOLL_TRIES=3\nPOLL_S=0\n'
        'kill() { echo "TEST GUARD: refused kill $*" >&2; return 1; }\n'
        "stop_detached_engine() { :; }\nstop_stray_engines() { :; }\nwait_for_port_free() { :; }\n"
        f'{funcs}\n{traps}\nAPP_CONTENTS_INODE=$(stat -f %i "$APP/Contents")\n{tail}\n'
    )
    runner = tmp / "run.sh"
    runner.write_text(script)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "TMPDIR": str(tmp)}
    done = subprocess.run(["/bin/bash", str(runner)], capture_output=True, text=True, timeout=60, env=env)
    return done, calls.read_text().splitlines() if calls.exists() else [], app


def _swap_segment() -> str:
    text = harness.SCRIPT.read_text(encoding="utf-8")
    return text[text.index('mkdir "$OLD"\n'): text.index('touch "$APP"')]


def test_a_failed_move_after_the_swap_rolls_back_and_relaunches_the_old_app(tmp_path: Path) -> None:
    done, calls, app = _run(tmp_path, "OLD_APP_STOPPED=1\n" + _swap_segment(), mv_fails=True)
    assert done.returncode == 2, done.stdout + done.stderr
    assert "ROLLBACK done" in done.stdout, done.stdout + done.stderr
    assert _installed_version(app) == OLD_VERSION, "the new Contents were left in place"
    assert any(c.startswith("launchctl bootstrap") for c in calls), calls


def test_a_good_move_after_the_swap_does_not_roll_back(tmp_path: Path) -> None:
    done, calls, app = _run(tmp_path, "OLD_APP_STOPPED=1\n" + _swap_segment() + "ROLLBACK_ARMED=0\nexit 0")
    assert done.returncode == 0 and "ROLLBACK" not in done.stdout, done.stdout + done.stderr
    assert _installed_version(app) == NEW_VERSION
    assert not any(c.startswith("launchctl bootstrap") for c in calls), calls


def test_a_signal_right_after_the_swap_never_restarts_the_new_contents(tmp_path: Path) -> None:
    swap = f'python3 -I "$SWAP_HELPER" "$APP/Contents" "$STAGED_APP/Contents"\nOLD_APP_STOPPED=1\nexit 143\n'
    done, calls, app = _run(tmp_path, swap)
    assert done.returncode == 143, done.stdout + done.stderr
    assert "RESTART:" not in done.stdout, done.stdout
    assert "ROLLBACK done" in done.stdout, done.stdout + done.stderr
    assert _installed_version(app) == OLD_VERSION
    assert any(c.startswith("launchctl bootstrap") for c in calls), calls


def test_a_failure_before_the_swap_still_just_restarts(tmp_path: Path) -> None:
    done, calls, app = _run(tmp_path, "OLD_APP_STOPPED=1\nexit 2\n")
    assert done.returncode == 2 and "RESTART done" in done.stdout and "ROLLBACK" not in done.stdout, done.stdout + done.stderr
    assert _installed_version(app) == OLD_VERSION
    assert any(c.startswith("launchctl bootstrap") for c in calls), calls


def _gap_points() -> list[int]:
    lines = _swap_segment().splitlines()
    points, depth = [], 0
    for i, line in enumerate(lines):
        if depth == 0:
            points.append(i)
        depth += line.startswith("if ")
        depth -= line == "fi"
    first_fi = next(i for i, l in enumerate(lines) if l == "fi")
    return [p for p in points if p > first_fi] + [len(lines)]


def test_a_signal_between_any_two_lines_after_the_swap_still_rolls_back(tmp_path: Path) -> None:
    lines = _swap_segment().splitlines()
    for n, at in enumerate(_gap_points()):
        work = tmp_path / f"gap{n}"
        work.mkdir()
        body = "\n".join(lines[:at] + ["exit 143"] + lines[at:])
        done, calls, app = _run(work, "OLD_APP_STOPPED=1\n" + body + "\n", mv_fails=False)
        where = f"after line {at}: {lines[at - 1]!r}"
        assert done.returncode == 143, where + done.stdout + done.stderr
        assert _installed_version(app) == OLD_VERSION, where + "\n" + done.stdout + done.stderr
        assert any(c.startswith("launchctl bootstrap") for c in calls), where
        assert "RESTART:" not in done.stdout, where


def test_a_same_version_reinstall_is_detected_by_inode(tmp_path: Path) -> None:
    swap = 'python3 -I "$SWAP_HELPER" "$APP/Contents" "$STAGED_APP/Contents"\nOLD_APP_STOPPED=1\nexit 143\n'
    done, calls, app = _run(tmp_path, swap, staged_version=OLD_VERSION)
    assert done.returncode == 143 and "ROLLBACK done" in done.stdout and "RESTART:" not in done.stdout, done.stdout + done.stderr
