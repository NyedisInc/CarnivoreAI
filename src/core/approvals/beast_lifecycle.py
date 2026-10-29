
from __future__ import annotations

from pathlib import Path

import structlog

from src.core.mcp import beast_mode

logger = structlog.get_logger()

SHUTDOWN_MARKER: str = "beast-mode-shutdown-on"
LEGACY_MARKER: Path = Path("cplugs") / "beastmode" / "shutdown-on"


def _consume(path: Path) -> bool:
    try:
        present = path.is_file()
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("beast_marker_unreadable", error_type=type(exc).__name__)
        return False
    return present


def start(state_dir: Path) -> bool:
    state_dir = Path(state_dir)
    legacy = state_dir / LEGACY_MARKER
    warm = _consume(state_dir / SHUTDOWN_MARKER) | _consume(legacy)
    try:
        legacy.parent.rmdir()
    except OSError as exc:
        logger.debug("beast_legacy_folder_kept", error_type=type(exc).__name__)
    if warm or not beast_mode.stored_armed():
        return False
    logger.warning("beastmode_kept_armed", reason="started_without_clean_shutdown")
    return True


def stop(state_dir: Path) -> None:
    marker = Path(state_dir) / SHUTDOWN_MARKER
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("on\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("beast_marker_unwritable", error_type=type(exc).__name__)
