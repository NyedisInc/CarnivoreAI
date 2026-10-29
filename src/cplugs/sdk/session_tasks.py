
from typing import Any, Tuple

from src.core.session_status import STATUS_WORKING, STATUS_WORKING_SUBAGENT
from src.models.session_tasks import SessionTasks


def watch_and_reader(app_state: Any) -> Tuple[Any, Any]:
    from src.api.session_tasks_routes import watch_and_reader as core_watch_and_reader  # noqa: PLC0415

    return core_watch_and_reader(app_state)


async def tasks_for(info: Any, reader: Any) -> SessionTasks:
    from src.core.session_tasks.service import tasks_for as core_tasks_for  # noqa: PLC0415

    return await core_tasks_for(info, reader)


__all__ = ["STATUS_WORKING", "STATUS_WORKING_SUBAGENT", "SessionTasks", "tasks_for", "watch_and_reader"]
