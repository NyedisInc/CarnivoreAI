
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.tmux_backend import TmuxBackend
from src.core.tmux_control import route
from tests.python.tmux_transport.test_transport_injection import RecordingTransport


@pytest.mark.asyncio
async def test_a_remote_backend_write_is_handed_back_without_touching_the_local_control_client(
        monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list = []
    monkeypatch.setattr(route, "control_input_enabled", lambda: True)
    monkeypatch.setattr(route, "get_control_input", lambda socket: asked.append(socket))
    backend = TmuxBackend("s1", Path("/tmp"), socket_name="carnivore-remote", transport=RecordingTransport())
    assert await route.write(backend, b"ls\r") == b"ls\r"
    assert asked == []
