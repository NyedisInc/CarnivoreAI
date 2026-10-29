
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_adopt_pid_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_adopt_pid_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.session_manager import SessionManager
from src.models import AdoptSessionResponse
from tests.socket_guard import TEST_SOCKET_NAME


@pytest.mark.asyncio
async def test_adopt_response_payload_carries_real_pty_pid():
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    sm._resolve_external_cwd = AsyncMock(return_value=Path("/tmp"))  # type: ignore[assignment]

    fake_backend = MagicMock()
    fake_backend.attach_existing = AsyncMock(return_value=None)
    fake_backend.capture_scrollback = MagicMock(return_value=b"")
    fake_backend.tmux_session = "external_target"
    fake_backend._pipe_path = Path("/tmp/does_not_exist_for_test.pipe")
    fake_backend.pid = 4212

    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external",
        return_value=fake_backend,
    ), patch(
        "src.core.session_manager.settings"
    ) as mock_settings:
        auth_cfg = MagicMock()
        auth_cfg.session.tmux_socket_name = TEST_SOCKET_NAME
        auth_cfg.session.scrollback_lines = 3000
        mock_settings.load_auth_config.return_value = auth_cfg

        result = await sm.adopt_external_session(
            "external_target", confirm_detach=False
        )

    response = AdoptSessionResponse(**result)

    assert response.session.pty_pid == 4212, (
        "AdoptSessionResponse.session.pty_pid must carry the live pane "
        f"pid, got {response.session.pty_pid!r}"
    )

    dumped = response.model_dump(mode="json")
    assert dumped["session"]["pty_pid"] == 4212


@pytest.mark.asyncio
async def test_adopt_response_falls_back_to_none_when_backend_has_no_pid():
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    sm._resolve_external_cwd = AsyncMock(return_value=Path("/tmp"))  # type: ignore[assignment]

    fake_backend = MagicMock()
    fake_backend.attach_existing = AsyncMock(return_value=None)
    fake_backend.capture_scrollback = MagicMock(return_value=b"")
    fake_backend.tmux_session = "external_target2"
    fake_backend._pipe_path = Path("/tmp/does_not_exist_for_test2.pipe")
    fake_backend.pid = None

    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external",
        return_value=fake_backend,
    ), patch(
        "src.core.session_manager.settings"
    ) as mock_settings:
        auth_cfg = MagicMock()
        auth_cfg.session.tmux_socket_name = TEST_SOCKET_NAME
        auth_cfg.session.scrollback_lines = 3000
        mock_settings.load_auth_config.return_value = auth_cfg

        result = await sm.adopt_external_session(
            "external_target2", confirm_detach=False
        )

    response = AdoptSessionResponse(**result)
    assert response.session.pty_pid is None


@pytest.mark.asyncio
async def test_create_session_response_already_carries_real_pty_pid():
    from src.core.tmux_backend import TmuxBackend

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()

    fake_backend = MagicMock(spec=TmuxBackend)
    fake_backend.start = AsyncMock(return_value=None)
    fake_backend.pid = 4285
    fake_backend.tmux_session = "cloude_createtest"

    with patch(
        "src.core.session_manager.build_backend", return_value=fake_backend
    ), patch("src.core.session_manager.settings") as mock_settings:
        mock_settings.load_auth_config.return_value = MagicMock()
        mock_settings.get_agent_command.return_value = "claude"

        session = await sm.create_session(
            session_id="ses_createtest",
            working_dir="/tmp",
            auto_start_claude=False,
        )

    assert session.pty_pid == 4285, (
        f"create_session response must carry the real pid, got {session.pty_pid!r}"
    )
