
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tests_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tests_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.pane_locale import is_utf8_locale
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)


@pytest.fixture
def locale_free_environ(monkeypatch):
    for var in ("LANG", "LC_ALL", "LC_CTYPE"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def tmux_socket():
    name = derive_test_socket("locale")
    yield name
    subprocess_kill = shutil.which("tmux")
    if subprocess_kill:
        os.system(f"{subprocess_kill} -L {name} kill-server >/dev/null 2>&1")


def _pane_lang(backend: TmuxBackend) -> str:
    rc, out, _ = backend._run_tmux_sync(
        "show-environment",
        "-t",
        backend.tmux_session,
        "LANG",
        check=False,
    )
    if rc != 0:
        return ""
    line = out.decode("utf-8", errors="replace").strip()
    return line.split("=", 1)[1] if "=" in line else ""


@requires_tmux
def test_first_and_subsequent_sessions_both_get_a_utf8_locale(
    locale_free_environ, tmux_socket
):
    backends = [
        TmuxBackend(
            session_id=f"loc{n}-{uuid.uuid4().hex[:6]}",
            working_dir=Path(tempfile.gettempdir()),
            on_output=None,
            socket_name=tmux_socket,
        )
        for n in (1, 2)
    ]

    async def _inner():
        for backend in backends:
            await backend.start(command="/bin/sh -c 'sleep 20'")
        return [_pane_lang(b) for b in backends]

    try:
        first, second = asyncio.run(_inner())
    finally:
        for backend in backends:
            asyncio.run(backend.stop())

    assert is_utf8_locale(first), f"first session LANG={first!r}"
    assert is_utf8_locale(second), f"second session LANG={second!r}"


@requires_tmux
def test_multibyte_output_is_not_mangled_in_the_pane(locale_free_environ, tmux_socket):
    if shutil.which("zsh") is None:
        pytest.skip("zsh not available")

    script = Path(tempfile.gettempdir()) / f"cc_mb_{uuid.uuid4().hex[:6]}.zsh"
    script.write_text("_enhanced_path() {\n  print -r -- $'\\u2192'\n}\n_enhanced_path\n")

    backend = TmuxBackend(
        session_id=f"mb-{uuid.uuid4().hex[:6]}",
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=tmux_socket,
    )

    async def _inner():
        await backend.start(command=f"/bin/zsh -f {script}; sleep 20")
        await asyncio.sleep(1.0)
        return backend.capture_scrollback(lines=20).decode("utf-8", errors="replace")

    try:
        text = asyncio.run(_inner())
    finally:
        asyncio.run(backend.stop())
        script.unlink(missing_ok=True)

    assert "character not in range" not in text, text[:200]
    assert "\u2192" in text, text[:200]
