import json
import os
import subprocess
import sys
import time
from pathlib import Path

from src.core.dev_lease import make_owner_check, start_watch

REPO = Path(__file__).resolve().parents[3]


def test_server_exits_when_lease_released(tmp_path):
    lease = tmp_path / "lease"
    lease.mkdir()
    (lease / "holder").write_text(json.dumps({"pid": os.getpid(), "at": time.time()}))
    env = {**os.environ, "CARNIVORE_TESTSRV_LEASE_DIR": str(lease), "CARNIVORE_DEV_LEASE_TTL_S": "1", "PYTHONPATH": str(REPO)}
    code = "from src.core.dev_lease import start_watch; start_watch(); import time; time.sleep(60)"
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=REPO, env=env)
    try:
        time.sleep(2.5)
        assert proc.poll() is None
        (lease / "holder").unlink()
        lease.rmdir()
        assert proc.wait(timeout=10) != 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_installed_server_has_no_watchdog():
    installed = Path("~/Library/Application Support/Carnivore Menubar/server").expanduser()
    assert make_owner_check(installed, {}) is None
    assert start_watch(installed, {}) is None
