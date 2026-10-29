
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from src.api.automation_timers_listing import is_local
from src.core.session_roles import read as roles_read
from src.models import SessionInfo


async def mark_session_roles(app_state: Any, infos: Iterable[Any], asleep: Optional[List[Dict[str, Any]]] = None) -> None:
    rows = [i for i in infos if isinstance(i, SessionInfo)]
    owned = [i for i in rows if is_local(i)]
    for info in rows:
        info.task_lead = info.do_not_disturb = None
    try:
        roles = await roles_read.read(app_state, owned, asleep)
    except roles_read.SessionRolesUnreadable:
        return
    if roles is None:
        return
    for info in owned:
        flags = roles.get(info.session.id)
        if flags is not None:
            info.task_lead, info.do_not_disturb = bool(flags.get("lead")), bool(flags.get("dnd"))
