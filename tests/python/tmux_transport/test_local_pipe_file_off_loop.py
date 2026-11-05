
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from src.core.tmux_transport import local
from src.core.tmux_transport.local import LocalTransport


def test_ensure_pipe_file_runs_off_the_loop_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    real = local._ensure_file

    def spy(path: Path, truncate: bool) -> None:
        seen.append(threading.get_ident())
        real(path, truncate)

    monkeypatch.setattr(local, "_ensure_file", spy)
    target = tmp_path / "deep" / "mirror"

    async def run() -> int:
        await LocalTransport().ensure_pipe_file(target, str(target), truncate=True)
        return threading.get_ident()

    loop_thread = asyncio.run(run())
    assert target.exists() and target.read_bytes() == b""
    assert seen and seen[0] != loop_thread


def test_ensure_pipe_file_keeps_existing_bytes_unless_truncating(tmp_path: Path) -> None:
    target = tmp_path / "mirror"
    target.write_bytes(b"keep")
    transport = LocalTransport()
    asyncio.run(transport.ensure_pipe_file(target, str(target), truncate=False))
    assert target.read_bytes() == b"keep"
    asyncio.run(transport.ensure_pipe_file(target, str(target), truncate=True))
    assert target.read_bytes() == b""
    assert asyncio.run(transport.pipe_file_exists(str(target))) is True
    assert asyncio.run(transport.pipe_file_exists(str(tmp_path / "gone"))) is False
