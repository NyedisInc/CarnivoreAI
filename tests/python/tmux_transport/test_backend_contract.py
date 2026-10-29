
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core.hosts.identity import is_remote_backend
from src.core.hosts.remote_backend import make_remote_backend
from src.core.session_backend import SessionBackend
from src.core.tmux_backend import TmuxBackend

SRC = Path(__file__).resolve().parents[3] / "src"
READER_OWNERS = {"session_backend.py", "tmux_backend.py", "pty_session.py"}


def test_the_contract_declares_what_callers_use() -> None:
    for name in ("tmux_session", "socket_name", "host_key", "is_remote", "detach_reader"):
        assert hasattr(SessionBackend, name), name


def test_is_remote_follows_the_class_through_the_contract() -> None:
    local = TmuxBackend("s1", Path("/tmp"))
    assert local.is_remote is False and is_remote_backend(local) is False
    assert is_remote_backend(MagicMock()) is False
    assert is_remote_backend(None) is False
    host = SimpleNamespace(socket="far", host_key="studio")
    remote = make_remote_backend(host, "s2", Path("/far"))
    assert remote.is_remote is True and remote.host_key == "studio" and is_remote_backend(remote) is True


@pytest.mark.asyncio
async def test_detach_reader_cancels_a_live_task_and_clears_the_fields() -> None:
    backend = TmuxBackend("s1", Path("/tmp"))
    backend._running = True
    backend._reader_task = asyncio.create_task(asyncio.sleep(60))
    task = backend._reader_task
    assert backend.detach_reader() is True
    assert backend._reader_task is None and backend._running is False
    with pytest.raises(asyncio.CancelledError):
        await task


def test_detach_reader_is_a_no_op_with_no_reader() -> None:
    backend = TmuxBackend("s1", Path("/tmp"))
    assert backend.detach_reader() is False
    assert backend.detach_reader() is False


def _source_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "cplugs/huddle" not in p.as_posix()]


def test_no_module_outside_the_owners_writes_the_reader_fields() -> None:
    pattern = re.compile(r"\b(?!self\b)\w+\._(?:reader_task|running)\s*=(?!=)")
    offenders = [f"{p.relative_to(SRC)}:{n}" for p in _source_files() if p.name not in READER_OWNERS
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if pattern.search(line)]
    assert offenders == []


def test_no_hasattr_probe_for_a_tmux_only_backend_member() -> None:
    pattern = re.compile(r"hasattr\(\s*\w*(?:backend|candidate)\w*\s*,\s*[\"'](?:respawn|probe_respawn|_run_tmux|"
                         r"_reader_task|_running)[\"']")
    offenders = [f"{p.relative_to(SRC)}:{n}" for p in _source_files()
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if pattern.search(line)]
    assert offenders == []
