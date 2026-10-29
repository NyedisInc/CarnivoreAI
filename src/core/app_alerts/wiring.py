
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

from src.core import session_change_notice
from src.core.app_alerts import conditions, service


def install(app_state: Any, loop: asyncio.AbstractEventLoop, db_path: Path) -> None:

    def _publisher(frame: Dict[str, Any]) -> None:
        loop.call_soon_threadsafe(session_change_notice.publish, app_state, frame)

    service.configure(db_path, _publisher)
    conditions.start_runner()


def uninstall() -> None:
    conditions.stop_runner()
    service.configure(None, None)
