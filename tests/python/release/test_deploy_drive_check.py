
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "scripts" / "deploy-dmg.sh"
LIB = ROOT / "scripts" / "deploy" / "drive-check.sh"
TEXT = LIB.read_text()
DEPLOY_TEXT = DEPLOY.read_text()


def _func(name: str) -> str:
    start = TEXT.index(f"{name}() {{")
    return TEXT[start : TEXT.index("\n}\n", start) + 3]


def _line(var: str) -> str:
    return next(l for l in TEXT.splitlines() if l.startswith(f"{var}="))


def _run(root: Path, tmux: str = "") -> subprocess.CompletedProcess:
    script = f"""
set -euo pipefail
log() {{ echo "$*"; }}
V=9.9.9
TS=20261026T000000Z
{_line("EXIT_DRIVE_REFUSED")}
export TMUX='{tmux}'
{_func("in_cloude_tmux_tree")}
{_func("check_backup_drive")}
check_backup_drive '{root}'
echo AFTER
"""
    return subprocess.run(["bash", "-s"], input=script, capture_output=True, text=True)


def _code() -> int:
    return int(_line("EXIT_DRIVE_REFUSED").split("=", 1)[1])


def test_exit_code_is_distinct_from_the_other_failures() -> None:
    assert _code() not in (0, 1, 2, 3, 4)
    header = DEPLOY_TEXT.split("set -euo pipefail")[0]
    assert f"exit {_code()} (EXIT_DRIVE_REFUSED)" in header


def test_deploy_sources_the_library_and_runs_the_check_last() -> None:
    assert 'source "$(dirname "$0")/deploy/drive-check.sh"' in DEPLOY_TEXT
    lines = DEPLOY_TEXT.rstrip().splitlines()
    assert lines[-1] == 'check_backup_drive "$DRIVE_ROOT"'


def test_volume_of_maps_paths_to_their_volume() -> None:
    script = _func("volume_of") + """
volume_of /Volumes/Backup/releases/previews
volume_of /Volumes/Backup
volume_of /Users/x/backups || echo none
"""
    res = subprocess.run(["bash", "-s"], input=script, capture_output=True, text=True)
    assert res.stdout.split() == ["/Volumes/Backup", "/Volumes/Backup", "none"]


def test_standalone_run_skips_a_missing_drive(tmp_path: Path) -> None:
    res = subprocess.run(["bash", str(LIB), str(tmp_path / "gone")], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "skipped: not mounted" in res.stdout


def test_missing_drive_is_skipped_not_failed(tmp_path: Path) -> None:
    res = _run(tmp_path / "not-there")
    assert res.returncode == 0, res.stderr
    assert "skipped: not mounted" in res.stdout
    assert "AFTER" in res.stdout


def test_readable_drive_passes_and_leaves_no_probe(tmp_path: Path) -> None:
    drive = tmp_path / "drive"
    drive.mkdir()
    res = _run(drive)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "drive check ok" in res.stdout
    assert list(drive.iterdir()) == []


def test_unreadable_drive_exits_with_the_distinct_code_and_names_the_fix(tmp_path: Path) -> None:
    drive = tmp_path / "drive"
    drive.mkdir()
    drive.chmod(0o000)
    try:
        res = _run(drive, tmux="/private/tmp/tmux-501/cloude,1459,0")
    finally:
        drive.chmod(0o755)
    assert res.returncode == _code(), res.stdout + res.stderr
    assert "AFTER" not in res.stdout
    assert "DRIVE ACCESS REFUSED" in res.stdout
    assert "9.9.9" in res.stdout
    assert "switch Carnivore off and on in Full Disk Access" in res.stdout
    assert "inside the tmux -L cloude tree: yes" in res.stdout


def test_reports_when_not_inside_the_cloude_tree(tmp_path: Path) -> None:
    drive = tmp_path / "drive"
    drive.mkdir()
    res = _run(drive, tmux="/private/tmp/tmux-501/default,99,0")
    assert "inside the tmux -L cloude tree: no" in res.stdout
    res = _run(drive)
    assert "inside the tmux -L cloude tree: no" in res.stdout


def test_carnivore_socket_counts_as_the_tree(tmp_path: Path) -> None:
    drive = tmp_path / "drive"
    drive.mkdir()
    res = _run(drive, tmux="/private/tmp/tmux-501/carnivore,7,0")
    assert "inside the tmux -L cloude tree: yes" in res.stdout


def test_drive_check_sends_nothing_to_tmux() -> None:
    body = _func("check_backup_drive") + _func("in_cloude_tmux_tree")
    assert "run-shell" not in body and "send-keys" not in body
    assert not re.search(r"(^|\$\(|[|;&]|\bthen|\bdo)\s*tmux\b", body, re.M)
