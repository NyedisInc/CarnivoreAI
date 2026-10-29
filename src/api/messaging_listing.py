
from __future__ import annotations

from typing import Any, Iterable

from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import REMOTE_ID_PREFIX
from src.core.messaging import store
from src.models import SessionInfo
from src.models.sessions import MessagingMark


def mark_messaging(app_state: Any, infos: Iterable[Any]) -> None:
    for info in infos:
        if not isinstance(info, SessionInfo):
            continue
        if (info.host_key != LOCAL_HOST_KEY or str(info.session.id).startswith(REMOTE_ID_PREFIX)
                or info.origin_install_id is not None):
            continue
        mark = store.mark_for_row(info.session_row_id)
        info.messaging = MessagingMark(**mark) if mark else None
