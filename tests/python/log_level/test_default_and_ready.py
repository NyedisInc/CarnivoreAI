
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_loglevel_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_loglevel_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

# ruff: noqa: E402
from src.config.settings import Settings
from src.core.log_level import live, store

REPO_ROOT = Path(__file__).resolve().parents[3]

_CHILD = r"""
import logging
import src.main as main
from src.core.log_level import live
from src.core.server_log import redact
assert live.current_number() == logging.ERROR, live.current_number()
redact.install_stdlib_routing()
logging.getLogger("uvicorn.error").setLevel(logging.INFO)  # what uvicorn.Config(log_level="info") does
main.logger.info("plain_info_noise")
live.announce(main.logger, "application_ready")
logging.getLogger("uvicorn.error").info("Application startup complete.")
try:
    raise RuntimeError("boom")
except RuntimeError:
    main.logger.exception("startup_step_failed")
"""


def _env_example_level() -> str:
    for line in (REPO_ROOT / ".env.example").read_text().splitlines():
        if line.startswith("LOG_LEVEL="):
            return line.split("=", 1)[1].strip()
    return ""


def test_new_install_template_defaults_to_error() -> None:
    assert store.env_name(_env_example_level()) == "error"


def test_absent_log_level_keeps_info_for_existing_installs() -> None:
    assert Settings.model_fields["log_level"].default == "INFO"
    assert store.env_name(Settings.model_fields["log_level"].default) == "info"
    assert live.DEFAULT_LEVEL == "info"


def test_readiness_markers_print_at_level_error(tmp_path: Path) -> None:
    env = dict(os.environ)
    env.update(
        LOG_LEVEL="ERROR",
        AUTH_CONFIG_FILE=str(tmp_path / "config.json"),
        CARNIVORE_STATE_DIR=str(tmp_path / "state"),
        PYTHONPATH=str(REPO_ROOT),
    )
    done = subprocess.run(
        [sys.executable, "-c", _CHILD], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    lines = done.stdout.splitlines()
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    names = [e.get("event") for e in events]
    assert "application_ready" in names
    assert [e["level"] for e in events if e.get("event") == "application_ready"] == ["info"]
    assert any("Application startup complete" in line for line in lines)
    assert "plain_info_noise" not in names
    failed = [e for e in events if e.get("event") == "startup_step_failed"]
    assert failed and failed[0]["level"] == "error"
    assert "RuntimeError" in json.dumps(failed[0])
