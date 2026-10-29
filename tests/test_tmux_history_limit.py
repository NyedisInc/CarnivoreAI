
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_adopt_rs_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_adopt_rs_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.tmux_backend import HISTORY_LIMIT, TmuxBackend


class _RecordingBackend(TmuxBackend):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tmux_calls: list = []

    async def _run_tmux(self, *args, **kwargs):
        self.tmux_calls.append(list(args))
        return 0, b"", b""


@pytest.mark.asyncio
async def test_history_limit_is_declared_before_the_pane_exists() -> None:
    backend = _RecordingBackend(
        session_id="probe", working_dir=Path("/tmp"), socket_name="ccwt_unit"
    )
    assert list(backend._history_limit_command()) == [
        "set-option", "-g", "history-limit", str(HISTORY_LIMIT)
    ]
    assert backend.tmux_calls == []
    assert HISTORY_LIMIT == 50000


@pytest.mark.asyncio
async def test_history_limit_read_reports_could_not_determine() -> None:
    backend = _RecordingBackend(
        session_id="probe", working_dir=Path("/tmp"), socket_name="ccwt_unit"
    )

    async def _fail(*_args, **_kwargs):
        return 1, b"", b"no server running"

    backend._run_tmux = _fail  # type: ignore[assignment]
    assert await backend.read_history_limit() is None

    async def _garbage(*_args, **_kwargs):
        return 0, b"not-a-number\n", b""

    backend._run_tmux = _garbage  # type: ignore[assignment]
    assert await backend.read_history_limit() is None

    async def _good(*_args, **_kwargs):
        return 0, b"10000\n", b""

    backend._run_tmux = _good  # type: ignore[assignment]
    assert await backend.read_history_limit() == 10000
