
from __future__ import annotations

import asyncio
from typing import Any

from src.core import session_change_notice
from src.core.codex_helpers import constants as K
from src.core.codex_helpers import runtime


def install(app_state: Any, loop: asyncio.AbstractEventLoop) -> None:
    from src.core.sessions.codex_update import find_installed_codex, probe_version  # noqa: PLC0415

    frame = session_change_notice.build_structural_notice(K.NOTICE_REASON)

    def _wake_listing() -> None:
        loop.call_soon_threadsafe(session_change_notice.publish, app_state, dict(frame))

    runtime.install(find_installed_codex, probe_version, on_change=_wake_listing)


def uninstall() -> None:
    runtime.uninstall()
