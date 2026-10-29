
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tmux_socket_file import PERF_SOCKET_PREFIX, kill_server_and_unlink, refuse_live_socket

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = REPO_ROOT / "venv" / "bin" / "python3"

def _fresh_totp_secret() -> str:
    import pyotp

    return pyotp.random_base32()


def free_port(minimum: int = 5001) -> int:
    for _ in range(200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port >= minimum:
            return port
    raise RuntimeError("could not find a free port at or above the floor")


def _throwaway_socket_name() -> str:
    name = f"{PERF_SOCKET_PREFIX}{uuid.uuid4().hex[:12]}"
    refuse_live_socket(name)
    return name


@dataclass
class PerfServer:

    port: Optional[int] = None
    startup_timeout_s: float = 45.0
    tmux_socket_name: Optional[str] = None

    def __post_init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cc_perf_"))
        self.tmux_socket = self.tmux_socket_name or _throwaway_socket_name()
        refuse_live_socket(self.tmux_socket)
        self.totp_secret = _fresh_totp_secret()
        self.jwt_secret = secrets.token_hex(32)
        self.port = self.port or free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._proc: Optional[subprocess.Popen] = None
        self._work_dir = self.root / "work"
        self._state_dir = self.root / "state"
        self._log_dir = self.root / "logs"
        self._corpus_root = self.root / "corpus"
        for d in (self._work_dir, self._state_dir, self._log_dir, self._corpus_root):
            d.mkdir(parents=True, exist_ok=True)
        self._config_path = self.root / "config.json"
        self._write_config()


    def _write_config(self) -> None:
        config = {
            "jwt_expiry_minutes": 30,
            "session": {
                "backend": "tmux",
                "tmux_socket_name": self.tmux_socket,
                "scrollback_lines": 10000,
                "disable_alternate_screen": True,
            },
            "notifications": {"enabled": False},
            "agents": {"wrappers": [], "shell_command": "/bin/sh"},
            "relay": {"enabled": False},
        }
        self._config_path.write_text(json.dumps(config, indent=2))

    def _env(self) -> dict:
        env = {key: os.environ[key] for key in ("PATH", "LANG", "TMPDIR") if key in os.environ}
        private_home = self.root / "home"
        private_home.mkdir(exist_ok=True)
        env.update({"HOME": str(private_home), "SHELL": "/bin/sh", "ZDOTDIR": str(private_home)})
        env.update(
            {
                "DEFAULT_WORKING_DIR": str(self._work_dir),
                "LOG_DIRECTORY": str(self._log_dir),
                "CLOUDE_STATE_DIR": str(self._state_dir),
                "CARNIVORE_SETTINGS_ENV_FILE": str(self.root / "unused.env"),
                "TOTP_SECRET": self.totp_secret,
                "JWT_SECRET": self.jwt_secret,
                "AUTH_CONFIG_FILE": str(self._config_path),
                "HOST": "127.0.0.1",
                "PORT": str(self.port),
                "CLOUDE_BOUND_HOST": "127.0.0.1",
                "CLOUDE_TEST_MODE": "1",
                "CLOUDE_CORPUS_INGEST": "0",
                "CLOUDE_DB_INTEGRITY_CHECK": "0",
                "CLOUDE_CORPUS_ROOT": str(self._corpus_root),
                "LOG_LEVEL": "WARNING",
            }
        )
        return env

    def start(self) -> "PerfServer":
        python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
        self._server_log = (self._log_dir / "server.log").open("w+")
        self._proc = subprocess.Popen(
            [
                python,
                "-m",
                "uvicorn",
                "src.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=str(REPO_ROOT),
            env=self._env(),
            stdout=self._server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.boot_started_at = time.monotonic()
        deadline = self.boot_started_at + self.startup_timeout_s
        import httpx

        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                self._server_log.flush()
                out = (self._log_dir / "server.log").read_text()
                raise RuntimeError(
                    "perf server process exited during startup "
                    f"(code {self._proc.returncode}); output:\n{out[-4000:]}"
                )
            try:
                resp = httpx.get(f"{self.base_url}/health", timeout=1.0)
                if resp.status_code == 200:
                    self.boot_ready_at = time.monotonic()
                    self.boot_seconds = self.boot_ready_at - self.boot_started_at
                    return self
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_error = exc
            time.sleep(0.05)
        raise RuntimeError(
            f"perf server never answered /health within {self.startup_timeout_s}s: "
            f"{last_error}"
        )

    @property
    def work_dir(self) -> str:
        return str(self._work_dir)

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None


    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            self._proc = None
        if getattr(self, "_server_log", None) is not None:
            self._server_log.close()
        refuse_live_socket(self.tmux_socket)
        kill_server_and_unlink(self.tmux_socket)
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "PerfServer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
