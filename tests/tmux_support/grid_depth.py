
from __future__ import annotations

import subprocess
import time

STOCK_DEPTH = 2000

TRIM_FLOOR = 0.9

OVERFLOW_MARGIN = 5000

FLOOD_TIMEOUT_SECONDS = 30.0


def flood_command(history_limit: int) -> str:
    lines = history_limit + OVERFLOW_MARGIN
    return f"sh -c 'r=0; while :; do read _; seq 1 {lines}; r=$((r+1)); echo FLOODED-$r; done'"


def measured_depth(socket: str, session: str, rounds: int = 1) -> int:
    _tmux(socket, "send-keys", "-t", session, "Enter")
    marker = f"FLOODED-{rounds}"
    deadline = time.monotonic() + FLOOD_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = _tmux(socket, "capture-pane", "-p", "-t", session)
        if screen.returncode == 0 and marker in screen.stdout.split():
            size = _tmux(socket, "display-message", "-p", "-t", session, "#{history_size}")
            return int(size.stdout.strip()) if size.stdout.strip().isdigit() else -1
        time.sleep(0.1)
    return -1


def tmux_version() -> tuple[int, int]:
    try:
        out = subprocess.run(["tmux", "-V"], capture_output=True, text=True, check=False, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return (0, 0)
    digits = "".join(c if c.isdigit() or c == "." else " " for c in out).split()
    parts = digits[0].split(".") if digits else []
    return (int(parts[0]), int(parts[1])) if len(parts) >= 2 else (0, 0)


def is_stock_depth(depth: int) -> bool:
    return 0 <= depth <= STOCK_DEPTH


def is_full_depth(depth: int, history_limit: int) -> bool:
    return history_limit * TRIM_FLOOR <= depth <= history_limit


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True, text=True, check=False, timeout=20,
    )
