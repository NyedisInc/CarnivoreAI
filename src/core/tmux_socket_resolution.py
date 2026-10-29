
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional, Tuple

import structlog

from src.core.product_identity import TMUX_SOCKET_NAME, sockets_to_probe
from src.core.tmux_listing import TmuxListing

logger = structlog.get_logger()

CACHE_ATTR = "_resolved_legacy_probe_socket"


def configured_tmux_socket_name(settings_obj: Any) -> Optional[str]:
    from src.config.config_file import read_config

    try:
        config_path = Path(settings_obj.auth_config_file).expanduser()
        signature = _file_signature(config_path)
    except (OSError, AttributeError, TypeError):
        return None
    cached = _CONFIGURED_CACHE.get(str(config_path))
    if cached is not None and cached[0] == signature:
        return cached[1]
    try:
        raw = read_config(config_path)
    except (FileNotFoundError, ValueError):
        return None
    session_block = raw.get("session")
    value = session_block.get("tmux_socket_name") if isinstance(session_block, dict) else None
    value = value if isinstance(value, str) and value else None
    _CONFIGURED_CACHE[str(config_path)] = (signature, value)
    return value


_CONFIGURED_CACHE: dict = {}


def _file_signature(path: Path) -> Tuple[int, int, int, int]:
    st = path.stat()
    return (st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def resolve_probe_socket(
    manager: Any,
    configured: Optional[str],
    list_for_socket: Callable[[str], Tuple[str, TmuxListing]],
) -> Tuple[str, TmuxListing]:
    if configured:
        return list_for_socket(configured)

    cached = getattr(manager, CACHE_ATTR, None)
    if cached:
        return list_for_socket(cached)

    candidates = sockets_to_probe(None)
    first_actual: Optional[str] = None
    first_listing: Optional[TmuxListing] = None
    winner: Optional[str] = None
    winning_listing: Optional[TmuxListing] = None
    for index, socket_name in enumerate(candidates):
        actual_socket, listing = list_for_socket(socket_name)
        if index == 0:
            first_actual, first_listing = actual_socket, listing
        if listing.ok and len(listing.sessions) >= 1:
            winner, winning_listing = actual_socket, listing
            break

    if winner is None:
        winner, winning_listing = first_actual, first_listing
    elif winner != TMUX_SOCKET_NAME:
        logger.info(
            "legacy_tmux_socket_adopted",
            socket=winner,
            current_socket=TMUX_SOCKET_NAME,
        )

    try:
        setattr(manager, CACHE_ATTR, winner)
    except Exception:  # noqa: BLE001
        pass

    assert winner is not None and winning_listing is not None
    return winner, winning_listing
