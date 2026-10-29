"""
The marker is one file in the state directory. The plugin kept its own in ``<state>/cplugs/beastmode/shutdown-on``; that one is still consumed
and is removed with its folder when the folder is empty.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from src.core.mcp import beast_mode

logger = structlog.get_logger()

# state directory
SHUTDOWN_MARKER: str = "beast-mode-shutdown-on"
# state directory
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
    """The app is starting: consume the markers and keep an armed Beast armed. Output: True when it started armed with no clean shutdown before.

    Inputs: state_dir (the app state directory). Nothing is ever written to the switch.
    Example: start(Path("/state"))  # False after a clean shutdown; True (switch untouched, warning logged) after a crash with Beast armed
    """
    state_dir = Path(state_dir)
    legacy = state_dir / LEGACY_MARKER
    warm = _consume(state_dir / SHUTDOWN_MARKER) | _consume(legacy)
    try:
        legacy.parent.rmdir()
    except OSError as exc:  # the plugins page
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
