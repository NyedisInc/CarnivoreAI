
from __future__ import annotations

from typing import Any, Iterable

from src.config import settings
from src.core.descriptions import store
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.hosts.identity import REMOTE_ID_PREFIX
from src.models import SessionInfo


def mark_descriptions(app_state: Any, infos: Iterable[Any]) -> None:
    state_dir = settings.get_state_dir()
    for info in infos:
        if not isinstance(info, SessionInfo):
            continue
        if (info.host_key != LOCAL_HOST_KEY or str(info.session.id).startswith(REMOTE_ID_PREFIX)
                or info.origin_install_id is not None):
            continue
        info.short_description = store.short_for_row(info.session_row_id, state_dir)
