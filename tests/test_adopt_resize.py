
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_adopt_rs_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_adopt_rs_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.models import AdoptSessionRequest
from tests.socket_guard import TEST_SOCKET_NAME


def _auth_cfg() -> MagicMock:
    cfg = MagicMock()
    cfg.session.tmux_socket_name = TEST_SOCKET_NAME
    cfg.session.scrollback_lines = 3000
    return cfg


def _fake_backend(calls: list, name: str = "external_target") -> MagicMock:
    backend = MagicMock()
    backend.tmux_session = name
    backend.pid = 4242
    backend._pipe_path = Path("/tmp/does_not_exist_adopt_rs.pipe")

    async def _attach(**_kwargs) -> None:
        calls.append("attach")

    backend.attach_existing = AsyncMock(side_effect=_attach)
    backend.resize = MagicMock(side_effect=lambda c, r: calls.append(f"resize:{c}x{r}"))
    backend.capture_scrollback = MagicMock(
        side_effect=lambda *a, **k: (calls.append("capture"), b"")[1]
    )
    return backend


async def _adopt(calls: list, **kwargs) -> dict:
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        manager = SessionManager()
    manager._resolve_external_cwd = AsyncMock(return_value=Path("/tmp"))
    backend = _fake_backend(calls)
    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external", return_value=backend
    ), patch("src.core.session_manager.settings") as mock_settings:
        mock_settings.load_auth_config.return_value = _auth_cfg()
        return await manager.adopt_external_session("external_target", **kwargs)


@pytest.mark.asyncio
async def test_adopt_resizes_the_pane_to_the_client_grid() -> None:
    calls: list = []
    await _adopt(calls, initial_cols=163, initial_rows=46)
    assert "resize:163x46" in calls, calls


@pytest.mark.asyncio
async def test_adopt_resizes_before_capturing_scrollback() -> None:
    calls: list = []
    await _adopt(calls, initial_cols=163, initial_rows=46)
    assert calls.index("resize:163x46") < calls.index("capture"), calls
    assert calls.index("attach") < calls.index("resize:163x46"), calls


@pytest.mark.asyncio
async def test_adopt_without_dimensions_does_not_invent_any() -> None:
    calls: list = []
    await _adopt(calls)
    assert not [c for c in calls if c.startswith("resize")], calls


@pytest.mark.asyncio
async def test_adopt_with_only_one_dimension_declines() -> None:
    calls: list = []
    await _adopt(calls, initial_cols=163)
    assert not [c for c in calls if c.startswith("resize")], calls


@pytest.mark.asyncio
async def test_a_failed_resize_does_not_abort_the_adoption() -> None:
    calls: list = []
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        manager = SessionManager()
    manager._resolve_external_cwd = AsyncMock(return_value=Path("/tmp"))
    backend = _fake_backend(calls)
    backend.resize = MagicMock(side_effect=RuntimeError("tmux said no"))
    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external", return_value=backend
    ), patch("src.core.session_manager.settings") as mock_settings:
        mock_settings.load_auth_config.return_value = _auth_cfg()
        result = await manager.adopt_external_session(
            "external_target", initial_cols=163, initial_rows=46
        )
    assert "session" in result
    assert "capture" in calls


def test_adopt_request_carries_client_dimensions() -> None:
    body = AdoptSessionRequest(session_name="fs2", cols=163, rows=46)
    assert (body.cols, body.rows) == (163, 46)
    bare = AdoptSessionRequest(session_name="fs2")
    assert (bare.cols, bare.rows) == (None, None)


def test_adopt_setup_makes_the_session_resizable() -> None:
    src = (ROOT / "src" / "core" / "tmux_backend.py").read_text(encoding="utf-8")
    marker = "    async def attach_existing("
    body = src[src.index(marker):]
    body = body[: body.index("\n    async def ensure_pipe_pane(")]
    assert '"window-size", "manual"' in body
    assert '"aggressive-resize", "off"' in body
    assert "_history_limit_command" in body
    assert "external_session_window_size_not_manual" not in body
