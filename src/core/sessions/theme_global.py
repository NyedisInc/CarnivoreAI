
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import structlog

from src.core.session_theme_resolution import resolve_theme

logger = structlog.get_logger()

BlockReader = Callable[[], Dict[str, Any]]

ThemeReader = Callable[[], Optional[str]]


def read_global_theme(reader: Optional[ThemeReader]) -> Optional[str]:
    if reader is None:
        return None
    try:
        value = reader()
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        logger.warning("global_theme_read_failed", error=str(exc))
        return None
    return value if isinstance(value, str) and value else None


def theme_reader_over_block(block_reader: BlockReader) -> ThemeReader:

    def read() -> Optional[str]:
        block = block_reader()
        values = block.get("values") if isinstance(block, dict) else None
        if not isinstance(values, dict):
            return None
        value = values.get("theme")
        return value if isinstance(value, str) and value else None

    return read


def effective_theme(
    store: Any, working_dir: Any, tmux_name: Optional[str] = None
) -> Optional[str]:
    return resolve_theme(
        pinned=store.get_pin(tmux_name) if tmux_name else None,
        project_default=store.get_project_theme(working_dir),
        global_default=read_global_theme(
            getattr(store, "global_theme_reader", None)
        ),
    ).theme_id
