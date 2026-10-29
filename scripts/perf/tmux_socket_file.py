
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

PERF_SOCKET_PREFIX: str = "cloudeperf_"

LIVE_SOCKET_NAMES = ("carnivore", "cloude")


class LiveSocketRefused(RuntimeError):
    pass


def refuse_live_socket(name: str) -> None:
    if not name or name in LIVE_SOCKET_NAMES:
        raise LiveSocketRefused(f"refusing to use tmux socket {name!r}: it is (or may be) the live socket; use a throwaway name")


def tmux_socket_dir() -> Path:
    return Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}"


def tmux_socket_path(name: str) -> Path:
    return tmux_socket_dir() / name


def kill_server_and_unlink(
    name: str, run: Optional[Callable[..., subprocess.CompletedProcess]] = None
) -> None:
    run = run or subprocess.run
    try:
        run(["tmux", "-L", name, "kill-server"], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        tmux_socket_path(name).unlink()
    except FileNotFoundError:
        pass
