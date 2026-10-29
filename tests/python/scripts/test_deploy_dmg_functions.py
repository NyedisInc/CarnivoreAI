
from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "deploy-dmg.sh"


def _function(name: str) -> str:
    lines = SCRIPT.read_text().splitlines()
    start = lines.index(f"{name}() {{")
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _bash(body: str, tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", body], capture_output=True, text=True, cwd=tmp_path, timeout=30)


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="sqlite3 CLI missing")
def test_backup_database_works_when_the_paths_contain_spaces_and_an_apostrophe(tmp_path: Path) -> None:
    state = tmp_path / "Application Support" / "Carn"
    state.mkdir(parents=True)
    with sqlite3.connect(state / "carnivore.db") as conn:
        conn.execute("CREATE TABLE t (a)")
        conn.execute("INSERT INTO t VALUES (1)")
    backup_dir = tmp_path / "Joe's backups" / "pre deploy"
    body = f"""set -euo pipefail
log() {{ echo "$*"; }}
STATE={str(state)!r}
BACKUP_DIR={str(backup_dir)!r}
{_function("backup_database")}
backup_database
"""
    result = _bash(body, tmp_path)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(backup_dir / "carnivore.db") as conn:
        assert conn.execute("SELECT a FROM t").fetchone() == (1,)


def _rollback_harness(tmp_path: Path, swap_ok: bool, bootstrap_ok: bool) -> subprocess.CompletedProcess:
    calls = tmp_path / "calls.txt"
    body = f"""set -uo pipefail
log() {{ echo "$*" >> {str(calls)!r}; }}
python3() {{ echo "swap $*" >> {str(calls)!r}; {'true' if swap_ok else 'false'}; }}
launchctl() {{ echo "launchctl $*" >> {str(calls)!r}; {'true' if bootstrap_ok else 'false'}; }}
sleep() {{ :; }}
boot_out_all_carnivore_jobs() {{ echo bootout >> {str(calls)!r}; }}
stop_detached_engine() {{ echo stopengine >> {str(calls)!r}; }}
wait_for_port_free() {{ echo portfree >> {str(calls)!r}; }}
APP=/A.app; OLD_CONTENTS=/old/Contents; SWAP_HELPER=/h.py; CUR=1.0; PLIST=/p.plist; TS=t; UID=501
{_function("bootstrap_with_retries")}
{_function("rollback_install")}
rollback_install
echo "rc=$?" >> {str(calls)!r}
"""
    return _bash(body, tmp_path)


def test_rollback_swaps_the_previous_contents_back_then_restarts_them(tmp_path: Path) -> None:
    _rollback_harness(tmp_path, swap_ok=True, bootstrap_ok=True)
    lines = (tmp_path / "calls.txt").read_text().splitlines()
    order = [next(i for i, l in enumerate(lines) if l.startswith(p)) for p in ("bootout", "stopengine", "portfree", "swap", "launchctl bootstrap")]
    assert order == sorted(order)
    assert "swap -I /h.py /A.app/Contents /old/Contents" in lines
    assert lines[-1] == "rc=0"


def test_a_failed_swap_back_is_loud_and_names_where_the_old_contents_are(tmp_path: Path) -> None:
    _rollback_harness(tmp_path, swap_ok=False, bootstrap_ok=True)
    text = (tmp_path / "calls.txt").read_text()
    assert "ROLLBACK FAILED" in text and "/old/Contents" in text
    assert not [l for l in text.splitlines() if l.startswith("launchctl bootstrap")]
    assert text.rstrip().endswith("rc=1")


def test_a_bootstrap_that_fails_every_try_returns_nonzero(tmp_path: Path) -> None:
    _rollback_harness(tmp_path, swap_ok=True, bootstrap_ok=False)
    text = (tmp_path / "calls.txt").read_text()
    assert sum(1 for l in text.splitlines() if l.startswith("launchctl bootstrap")) == 5
    assert text.rstrip().endswith("rc=1")


def test_the_script_arms_rollback_after_the_swap_and_disarms_after_the_version_answers() -> None:
    source = SCRIPT.read_text()
    assert source.index("ROLLBACK_ARMED=1") < source.index('codesign --verify --deep --strict "$APP"')
    assert source.index("ROLLBACK_ARMED=0\n\nlog \"verify: no versioned") > source.index('if [ "$ver" != "v$V" ]')
