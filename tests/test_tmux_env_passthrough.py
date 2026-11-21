
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

requires_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")

LEAK_PROBE = "CC_ENV_LEAK_PROBE"


@pytest.fixture
def tmux_socket():
    name = derive_test_socket("envpass")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        os.system(f"{tmux} -L {name} kill-server >/dev/null 2>&1")


def _backend(socket: str) -> TmuxBackend:
    return TmuxBackend(
        session_id=f"env-{uuid.uuid4().hex[:6]}",
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=socket,
    )


def _session_env(backend: TmuxBackend, key: str) -> Optional[str]:
    rc, out, _ = backend._run_tmux_sync("show-environment", "-t", backend.tmux_session, key, check=False)
    line = out.decode("utf-8", errors="replace").strip()
    if rc != 0 or "=" not in line:
        return None
    return line.split("=", 1)[1]


def _start_all(sessions: list[tuple[TmuxBackend, Dict[str, str]]]) -> list[TmuxBackend]:

    async def go() -> None:
        for backend, env in sessions:
            await backend.start(command="/bin/sh -c 'sleep 20'", env=env)

    asyncio.run(go())
    return [b for b, _ in sessions]


def _stop_all(backends: list[TmuxBackend]) -> None:
    for backend in backends:
        asyncio.run(backend.stop())


@requires_tmux
def test_every_session_gets_its_own_overlay_not_the_servers_first_copy(tmux_socket: str) -> None:
    one, two = _backend(tmux_socket), _backend(tmux_socket)
    try:
        _start_all([(one, {"CLOUDECODE_SESSION_ID": "ses_first"}), (two, {"CLOUDECODE_SESSION_ID": "ses_second"})])
        assert _session_env(one, "CLOUDECODE_SESSION_ID") == "ses_first"
        assert _session_env(two, "CLOUDECODE_SESSION_ID") == "ses_second"
    finally:
        _stop_all([one, two])


@requires_tmux
def test_only_the_callers_keys_travel_not_the_whole_environment(tmux_socket: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LEAK_PROBE, "from-the-app")
    backend = _backend(tmux_socket)
    try:
        _start_all([(backend, {"CALLER_KEY": "mine"})])
        assert _session_env(backend, "CALLER_KEY") == "mine"
        assert _session_env(backend, LEAK_PROBE) is None
    finally:
        _stop_all([backend])


@requires_tmux
def test_a_value_with_a_newline_is_skipped_not_truncated(tmux_socket: str) -> None:
    backend = _backend(tmux_socket)
    try:
        _start_all([(backend, {"MULTILINE": "first\nsecond", "CARRIAGE": "a\rb", "FINE": "ok"})])
        assert _session_env(backend, "MULTILINE") is None
        assert _session_env(backend, "CARRIAGE") is None
        assert _session_env(backend, "FINE") == "ok"
    finally:
        _stop_all([backend])


@requires_tmux
def test_a_none_value_and_an_equals_in_a_key_are_skipped(tmux_socket: str) -> None:
    backend = _backend(tmux_socket)
    try:
        _start_all([(backend, {"NOTHING": None, "BAD=KEY": "x", "FINE": "ok"})])  # type: ignore[dict-item]
        assert _session_env(backend, "NOTHING") is None
        assert _session_env(backend, "FINE") == "ok"
    finally:
        _stop_all([backend])


@requires_tmux
def test_the_locale_still_travels_as_dash_e(tmux_socket: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LANG", "LC_ALL", "LC_CTYPE"):
        monkeypatch.delenv(var, raising=False)
    first, second = _backend(tmux_socket), _backend(tmux_socket)
    try:
        _start_all([(first, {}), (second, {})])
        for backend in (first, second):
            lang = _session_env(backend, "LANG")
            assert lang and "UTF-8" in lang.upper().replace("UTF8", "UTF-8"), lang
    finally:
        _stop_all([first, second])
