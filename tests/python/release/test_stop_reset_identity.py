
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
THROWAWAY_PORT = 45231

_LISTENER_SRC = (
    "import socket,sys,time\n"
    "s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen(5); print('up', flush=True); time.sleep(60)\n"
)


def _fake_checkout(root: Path) -> Path:
    (root / "scripts").mkdir(parents=True)
    for name in ("stop.sh", "reset.sh", "scripts/resolve-port.sh"):
        shutil.copy(REPO_ROOT / name, root / name)
    (root / "start.sh").write_text("#!/bin/bash\nexit 0\n")
    for name in ("stop.sh", "reset.sh", "start.sh"):
        (root / name).chmod(0o755)
    (root / ".env").write_text(f"PORT={THROWAWAY_PORT}\n")
    return root.resolve()


@pytest.mark.parametrize("script", ["stop.sh", "reset.sh"])
@pytest.mark.parametrize("from_this_checkout", [False, True])
def test_listener_is_stopped_only_when_it_runs_from_this_checkout(tmp_path, script, from_this_checkout):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", THROWAWAY_PORT)) == 0:
            pytest.skip(f"CANNOT DETERMINE: port {THROWAWAY_PORT} already has a listener")
    checkout = _fake_checkout(tmp_path / "checkout")
    elsewhere = (tmp_path / "elsewhere")
    elsewhere.mkdir()
    cwd = checkout if from_this_checkout else elsewhere.resolve()
    listener = subprocess.Popen(
        [sys.executable, "-c", _LISTENER_SRC, str(THROWAWAY_PORT), "-m", "src.main"], stdout=subprocess.PIPE, text=True, cwd=cwd
    )
    try:
        assert listener.stdout.readline().strip() == "up"
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp_path), "CLOUDE_LAUNCHD_LABEL": "no.such.job.for.this.test"}
        result = subprocess.run([str(checkout / script)], cwd=checkout, env=env, capture_output=True, text=True, timeout=60, check=False)
        time.sleep(0.5)
        if from_this_checkout:
            assert listener.poll() is not None, f"{script} left this checkout's own engine running\n{result.stdout}"
        else:
            assert listener.poll() is None, f"{script} killed a src.main listener of another folder\n{result.stdout}"
            assert f"left alone: PID {listener.pid}" in result.stdout, result.stdout
        if script == "stop.sh" and not from_this_checkout:
            assert result.returncode == 0, result.stdout + result.stderr
    finally:
        listener.kill()
        listener.wait()
