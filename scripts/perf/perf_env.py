"""Boot and tear down one ISOLATED, real Cloude Code server for measurement.

WHY A REAL SUBPROCESS, NOT AN IN-PROCESS TEST APP. Every existing test
harness that boots "the app" (``tests/real_hook_app.py``,
``tests/test_setup_wizard_renders.py``) deliberately assembles a MINIMAL
FastAPI app with only the routers a given test needs, specifically to
avoid ``src.main.py``'s full lifespan (config/db migration, first-run
import, boot re-adopt). That is the right call for those files, and the
wrong one here: this harness has to measure settings, the archive, menus
and notifications as well as the terminal, and it has to report the
SERVER PROCESS's own idle CPU and memory - both of which need the real
``src.main:app``, in its own OS process, so a ``ps`` sample against its
pid means what it claims to mean. A thread inside the measuring process
would have its CPU time and the browser driver's CPU time on the same
number.

ISOLATION, ENFORCED BY CONSTRUCTION, NOT BY CONVENTION.

  - Its tmux traffic never reaches the live ``cloude`` socket:
    ``session.tmux_socket_name`` in this run's throwaway ``config.json``
    is a name generated fresh per run (``_throwaway_socket_name``), and it
    is asserted not to equal ``cloude``. No live socket is queried.
  - Its state, working directory, logs and datastore all live under one
    ``tempfile.mkdtemp()`` root, never under the real state directory a
    running Electron app would be using.
  - ``CLOUDE_TEST_MODE=1`` turns off the corpus ingest loop and the daily
    integrity-check loop (both default OFF under it - see
    ``src/core/corpus_ingest_task.py`` / ``src/core/db_integrity.py``), so
    this run never walks the operator's real ``~/.claude/projects`` corpus
    and never opens a database this harness did not create.
  - Every agent this run launches is a bare shell, never ``claude``. See
    the module docstring on ``scripts/perf/run_baseline.py`` for why: it
    keeps the baseline deterministic and free of real LLM latency, which
    the plan requires be measured SEPARATELY in the first place.
  - The developer's own ``.env`` in the checkout root, if one exists, is
    never read. ``Settings`` (``src/config/settings.py``) resolves its
    ``env_file`` relative to the subprocess's cwd, which is
    ``REPO_ROOT`` - not this run's throwaway root - so a whitelisted
    ``os.environ`` alone cannot stop it from also picking up whatever
    else the developer's ``.env`` sets (a real provider key, a real
    ``DEFAULT_WORKING_DIR``, ``CLOUDE_DEV_RELOAD``). ``_env()`` instead
    points ``CARNIVORE_SETTINGS_ENV_FILE`` at a path under this run's own
    root that is never created, so ``Settings`` always resolves its
    dotenv source to a missing file - a silent no-op - regardless of
    what the checkout root holds.

The subprocess binds loopback only. Its fresh authentication fixture and
private socket/state/home are never shared with production clients.
"""

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

from tmux_socket_file import PERF_SOCKET_PREFIX, kill_server_and_unlink

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = REPO_ROOT / "venv" / "bin" / "python3"

FORBIDDEN_SOCKET_NAME = "cloude"

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
    assert name != FORBIDDEN_SOCKET_NAME, "generated name collided with the live socket"
    return name


@dataclass
class PerfServer:

    port: Optional[int] = None
    startup_timeout_s: float = 45.0
    tmux_socket_name: Optional[str] = None

    def __post_init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cc_perf_"))
        self.tmux_socket = self.tmux_socket_name or _throwaway_socket_name()
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
        assert self.tmux_socket != FORBIDDEN_SOCKET_NAME
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
        assert self.tmux_socket != FORBIDDEN_SOCKET_NAME
        kill_server_and_unlink(self.tmux_socket)
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "PerfServer":
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


def assert_no_live_socket_named(name: str) -> None:
    assert name != FORBIDDEN_SOCKET_NAME, (
        "refusing to run against the live 'cloude' tmux socket - this "
        "harness must use its own throwaway socket"
    )
