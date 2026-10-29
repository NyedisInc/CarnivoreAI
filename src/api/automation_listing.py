
from __future__ import annotations

from typing import Any, Iterable

from src.core.automations import run_sessions
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import REMOTE_ID_PREFIX
from src.models import SessionInfo
from src.models.sessions import AutomationMark


def mark_automation(app_state: Any, infos: Iterable[Any]) -> None:
    for info in infos:
        if not isinstance(info, SessionInfo):
            continue
        if (info.host_key != LOCAL_HOST_KEY or str(info.session.id).startswith(REMOTE_ID_PREFIX)
                or info.origin_install_id is not None):
            continue
        mark = run_sessions.mark_for_row(info.session_row_id)
        info.automation = AutomationMark(**mark) if mark else None
