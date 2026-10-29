
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from src.core.hosts.remote_backend import make_remote_backend
from src.core.tmux_backend import TmuxBackend
from src.core.hosts.remote_host import RemoteHostUnavailable
from src.core.sessions.errors import TmuxError


class _Host:

    host_key = "far"
    tmux_path = "/t"
    socket = "far-sock"
    login_path = "/usr/bin"
    command_timeout = 2.0
    is_up = True
    pipe_dir = "/far/pipes"
    loop = None

    def __init__(self, mirror_dir: Path) -> None:
        self.scripts: List[str] = []
        self.mirror_dir = mirror_dir

    def pipe_path(self, slug: str) -> str:
        return f"{self.pipe_dir}/{slug}.pipe"

    def mirror_path(self, slug: str) -> Path:
        return self.mirror_dir / slug

    async def exec(self, *, script: str = "", **_kwargs):
        self.scripts.append(script)
        return SimpleNamespace(returncode=0)

    async def command(self, verb, *args, timeout=None):
        return SimpleNamespace(ok=True, lines=(), number=1)


class _Stream:

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


def _backend(mirror_dir: Path) -> tuple[TmuxBackend, _Host, _Stream]:
    host = _Host(mirror_dir)
    backend = make_remote_backend(host, "ses_1", Path("/far/home"))  # type: ignore[arg-type]
    stream = _Stream()
    backend._lifecycle._stream = stream  # type: ignore[attr-defined]
    return backend, host, stream


def test_stop_after_detach_reader_still_closes_the_stream_and_removes_the_far_file(tmp_path: Path) -> None:
    backend, host, stream = _backend(tmp_path)
    backend._running = True
    backend._reader_task = None
    assert backend.detach_reader() is False
    asyncio.run(backend.stop())
    assert stream.stopped == 1
    assert any(s.startswith("rm -f ") for s in host.scripts)


def test_stop_twice_is_idempotent(tmp_path: Path) -> None:
    backend, host, stream = _backend(tmp_path)
    asyncio.run(backend.stop())
    asyncio.run(backend.stop())
    assert stream.stopped == 2 and len([s for s in host.scripts if s.startswith("rm -f ")]) == 2


def test_a_failed_create_removes_the_far_output_file(tmp_path: Path) -> None:
    backend, host, stream = _backend(tmp_path)

    async def refuse(*_a, **_k):
        return 1, "boom".encode()

    backend._spawn_session = refuse  # type: ignore[method-assign]
    with pytest.raises(TmuxError, match="new-session failed"):
        asyncio.run(backend.start("true"))
    assert any(s.startswith("rm -f ") for s in host.scripts)
    assert stream.stopped == 1


def test_a_start_on_a_running_backend_does_not_remove_its_file(tmp_path: Path) -> None:
    backend, host, _ = _backend(tmp_path)
    backend._running = True
    with pytest.raises(RuntimeError, match="already running"):
        asyncio.run(backend.start("true"))
    assert not any(s.startswith("rm -f ") for s in host.scripts)


def test_read_async_restarts_the_stream_while_the_reader_lives(tmp_path: Path) -> None:
    backend, _, stream = _backend(tmp_path)

    async def go() -> None:
        async def forever() -> None:
            await asyncio.sleep(60)

        backend._reader_task = asyncio.create_task(forever())
        await backend.read_async()
        backend._reader_task.cancel()

    asyncio.run(go())
    assert stream.started == 1
