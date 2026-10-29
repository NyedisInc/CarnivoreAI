
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from src.core.tmux_backend import TmuxBackend
from src.core.tmux_paste_buffer import unique_buffer_name
from tests.socket_guard import derive_test_socket


def test_two_loads_never_share_a_buffer_name() -> None:
    names = {unique_buffer_name("abc") for _ in range(50)}
    assert len(names) == 50
    assert all(n.startswith("cloude_abc_") for n in names)


@pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")
def test_overlapping_pastes_on_one_pane_both_arrive(tmp_path: Path) -> None:
    socket = derive_test_socket("paste_unique")
    base = ["tmux", "-L", socket, "-f", "/dev/null"]
    out = tmp_path / "out.txt"
    assert subprocess.run([*base, "new-session", "-d", "-s", "p1", "-x", "200", "-y", "50",
                           f"cat > {out}"], check=False).returncode == 0
    try:
        backend = TmuxBackend.for_external(session_name="p1", working_dir=tmp_path, on_output=None,
                                           socket_name=socket)
        backend._running = True
        first, second = b"A" * 400 + b"\n", b"B" * 400 + b"\n"
        async def both() -> None:
            await asyncio.gather(backend._write_via_paste_buffer(first),
                                 backend._write_via_paste_buffer(second))
        asyncio.run(both())
        time.sleep(0.5)
        got = out.read_bytes()
        assert first in got and second in got
    finally:
        subprocess.run([*base, "kill-server"], check=False)
