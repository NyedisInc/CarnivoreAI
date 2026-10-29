
from __future__ import annotations

import builtins
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_diag_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_diag_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import diagnostics_routes
from src.api.auth import require_auth
from src.config import settings
from src.core.diagnostics import builder, log_tails
from src.core.server_log import locate

FAKE_SECRET = "gh" + "p_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"
FORBIDDEN = ("carnivore.db", "cloude.db", "auth.json", "tui_auth.json", ".env")


@pytest.fixture()
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    for name in FORBIDDEN:
        (state / name).write_text("decoy " + FAKE_SECRET)
    log = tmp_path / "server.log"
    log.write_text(json.dumps({"event": "boom", "level": "error", "timestamp": "2026-10-17T00:00:00Z",
                               "detail": f"token {FAKE_SECRET} leaked"}) + "\n")
    banner = tmp_path / "banner.log"
    banner.write_text(f"startup failed with {FAKE_SECRET}")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"mcp": {"token": FAKE_SECRET}, "log_level": "info"}))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(log_tails, "LEGACY_TMP_GLOB", str(tmp_path / "no-such-*.log"))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(locate, "server_log_path", lambda: log)
    monkeypatch.setattr(builder, "STARTUP_ERROR_FILE", banner)
    monkeypatch.setattr(builder, "_run", lambda argv: None)
    monkeypatch.setattr(builder, "_tmux_for", lambda socket: "tmux")
    return state


def test_planted_secret_never_reaches_the_bundle(world):
    text = json.dumps(builder.build_bundle(mode="offline"))
    assert FAKE_SECRET not in text
    assert "boom" in text
    assert "mcp" in json.loads(text)["config"]["keys"] and "token" not in json.dumps(json.loads(text)["config"])


def test_redactor_failure_drops_the_section_and_says_so(world):
    def explode(_text: str) -> str:
        raise RuntimeError("redactor down")

    bundle = builder.build_bundle(mode="offline", redact=explode)
    assert bundle["startup_errors"] is None and bundle["config"] is None
    assert any("redaction failed" in note for note in bundle["notes"])
    assert FAKE_SECRET not in json.dumps(bundle)


def test_forbidden_files_are_never_opened(world, monkeypatch):
    opened = []
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

    def spy(real):
        def wrapper(file, *a, **kw):
            opened.append(str(file))
            return real(file, *a, **kw)
        return wrapper

    def no_sqlite(*a, **kw):
        raise AssertionError("diagnostics must not open a database")

    monkeypatch.setattr(builtins, "open", spy(real_open))
    monkeypatch.setattr(io, "open", spy(real_io_open))
    monkeypatch.setattr(os, "open", spy(real_os_open))
    monkeypatch.setattr(sqlite3, "connect", no_sqlite)
    builder.build_bundle(mode="server")
    touched = [p for p in opened if Path(p).name in FORBIDDEN]
    assert touched == []
    assert any(Path(p).name == "config.json" for p in opened), "the spy must be able to see opens"


def test_route_returns_the_bundle_and_needs_auth(world):
    app = FastAPI()
    app.include_router(diagnostics_routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    body = TestClient(app).get("/diagnostics").json()
    assert body["mode"] == "server" and body["process"]["pid"] == os.getpid()
    assert FAKE_SECRET not in json.dumps(body)
    app.dependency_overrides.clear()
    assert TestClient(app).get("/diagnostics").status_code in (401, 403)


def test_cli_prints_the_same_shaped_json(tmp_path):
    out = subprocess.run([sys.executable, "-m", "src.core.diagnostics"], capture_output=True, text=True,
                         timeout=60, cwd=Path(__file__).resolve().parents[3], check=False,
                         env={**os.environ, "STATE_DIR_OVERRIDE": str(tmp_path)})
    assert out.returncode == 0, out.stderr[-400:]
    bundle = json.loads(out.stdout)
    assert bundle["mode"] == "offline" and {"version", "tmux", "disk", "runtime", "notes"} <= set(bundle)


def test_a_failing_section_does_not_kill_the_bundle(world, monkeypatch):
    from src.config.errors import StateDirUnavailableError

    def boom():
        raise StateDirUnavailableError(Path("/nope"), OSError("denied"))

    monkeypatch.setattr(builder, "_disk", boom)
    monkeypatch.setitem(builder._SECTIONS, "disk", boom)
    bundle = builder.build_bundle(mode="server")
    assert bundle["disk"] is None and bundle["version"] is not None
    assert any(n.startswith("disk: not measured") for n in bundle["notes"])


def test_offline_bundle_creates_and_renames_nothing(tmp_path, monkeypatch):
    home = tmp_path / "home"
    legacy = home / "Library" / "Application Support" / "CloudeCode"
    legacy.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(settings, "state_dir_override", None)
    monkeypatch.setattr(settings, "auth_config_file", str(tmp_path / "missing.json"))
    bundle = builder.build_bundle(mode="offline")
    assert bundle["disk"]["path"].endswith("CloudeCode")
    assert legacy.is_dir() and not (legacy.parent / "Carnivore").exists()
    monkeypatch.setattr(builder, "locate_state_dir", lambda: None)
    monkeypatch.setitem(builder._SECTIONS, "disk", builder._disk)
    assert builder.build_bundle(mode="offline")["disk"] is None
    assert not (home / "Library" / "Application Support" / "Carnivore").exists()


def test_config_is_never_loaded_through_the_settings_models(world, monkeypatch):
    def forbidden(self):
        raise AssertionError("load_auth_config must not be called")

    monkeypatch.setattr(type(settings), "load_auth_config", forbidden)
    assert builder.build_bundle(mode="server")["tmux"]["socket"]


@pytest.mark.parametrize("text,seconds", [("05:07", 307), ("01:02:03", 3723), ("2-00:00:01", 172801), ("bad", None)])
def test_etime_parses_the_macos_format(text, seconds):
    assert builder.parse_etime(text) == seconds


def test_a_hard_linked_startup_banner_is_not_read(tmp_path, monkeypatch):
    from src.core.diagnostics import builder
    from src.core.server_log import locate

    banner = tmp_path / "banner.log"
    banner.write_text("startup failed\n")
    monkeypatch.setattr(builder, "STARTUP_ERROR_FILE", banner)
    monkeypatch.setattr(locate, "server_log_path", lambda: tmp_path / "none.log")
    assert builder._startup_errors()["banner_tail"] == "startup failed\n"
    os.link(banner, tmp_path / "second-name.log")
    assert builder._startup_errors()["banner_tail"] is None
