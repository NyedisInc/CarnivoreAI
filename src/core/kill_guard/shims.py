
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import structlog

from src.config.errors import StateDirUnavailableError

from src.core.kill_guard.shim_template import SHIM_TEMPLATE

log = structlog.get_logger(__name__)

GUARD_DIR_NAME = "guard"
GUARDED_TOOLS = {"pkill": "/usr/bin/pkill", "killall": "/usr/bin/killall"}
REAL_PGREP = "/usr/bin/pgrep"
REAL_PS = "/bin/ps"
MAX_MATCHES = 10
MIN_PATTERN_LEN = 3
PROTECTED_NAMES = ("claude", "tmux", "Carnivore", "src.main", "bash", "zsh")
PROTECTED_PROCESS_REGEX = r"claude|tmux|carnivore|cloude|src\.main"


def render_shim(tool: str, real_tool: str, real_pgrep: str = REAL_PGREP, real_ps: str = REAL_PS) -> str:
    fills = {
        "@TOOL@": tool, "@REAL_TOOL@": real_tool, "@REAL_PGREP@": real_pgrep, "@REAL_PS@": real_ps,
        "@MAX_MATCHES@": str(MAX_MATCHES), "@MIN_PATTERN_LEN@": str(MIN_PATTERN_LEN),
        "@PROTECTED_NAMES@": " ".join(PROTECTED_NAMES), "@PROTECTED_PROCESS_REGEX@": PROTECTED_PROCESS_REGEX,
    }
    text = SHIM_TEMPLATE
    for marker, value in fills.items():
        text = text.replace(marker, value)
    return text


def guard_dir(state: Path) -> Path:
    return Path(state) / "bin" / GUARD_DIR_NAME


def _write_if_changed(target: Path, text: str) -> None:
    try:
        if target.read_text() == text and os.access(target, os.X_OK):
            return
    except OSError:
        pass
    tmp = target.with_name(target.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o755)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)


def ensure_guards(state: Path) -> Optional[Path]:
    folder = guard_dir(state)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for tool, real in GUARDED_TOOLS.items():
            _write_if_changed(folder / tool, render_shim(tool, real))
    except OSError as exc:
        log.warning("kill_guard_write_failed", folder=str(folder), error=str(exc))
        return None
    return folder


def pane_guard_dir() -> Optional[str]:
    from src.config import settings

    try:
        state = settings.get_state_dir()
    except (OSError, StateDirUnavailableError) as exc:
        log.warning("kill_guard_state_dir_unavailable", error=str(exc))
        return None
    folder = ensure_guards(state)
    return str(folder) if folder else None


def path_with_guard(path: str) -> str:
    folder = pane_guard_dir()
    if not folder:
        return path
    rest = [p for p in path.split(os.pathsep) if p and p != folder]
    return os.pathsep.join([folder, *rest])
