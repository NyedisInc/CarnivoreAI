from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _shim(tmp_path: Path, name: str, body: str) -> None:
    p = tmp_path / name
    p.write_text("#!/bin/bash\n" + body)
    p.chmod(0o755)


def _run_health(tmp_path: Path, host: str = "studio") -> tuple[int, str, str, str]:
    log = tmp_path / "ssh.log"
    curl_log = tmp_path / "curl.log"
    _shim(tmp_path, "ssh", f'printf "%s|%s\\n" "$1" "$2" >> "{log}"\nexec bash -c "$2"\n')
    _shim(
        tmp_path,
        "curl",
        f'echo "$*" >> "{curl_log}"\n'
        'case "$*" in *http://127.0.0.1:*) printf \'{"version":"1"}\\n__CODE__200\';; '
        '*) echo "connection refused" >&2; exit 7;; esac\n',
    )
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", "-c",
         f'. "{ROOT}/scripts/deploy-lib.sh"; . "{ROOT}/scripts/deploy-restart-check.sh"; '
         f'dl_health_json {host} 8000 5'],
        env=env, capture_output=True, text=True, timeout=30,
    )
    read = lambda p: p.read_text() if p.exists() else ""
    return r.returncode, r.stdout, read(log), read(curl_log)


def test_health_is_asked_on_the_target_loopback_over_ssh(tmp_path):
    rc, out, ssh_log, curl_log = _run_health(tmp_path)
    assert rc == 0 and out.startswith("200 "), out
    assert ssh_log.startswith("studio|curl "), ssh_log
    assert "http://127.0.0.1:8000/api/v1/health" in curl_log


def test_deploy_mini_installs_requirements_and_drops_the_lan_health_host():
    text = (ROOT / "scripts" / "deploy-mini.sh").read_text()
    assert "pip install -r requirements.txt" in text
    assert "HEALTH_HOST" not in text
    assert "CLOUDE_DEPLOY_SKIP_WEB_CHECK" in text
