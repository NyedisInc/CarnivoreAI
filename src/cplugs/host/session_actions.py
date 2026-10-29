
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import structlog

from src.cplugs.host import capabilities

logger = structlog.get_logger()


class AppRequest:

    def __init__(self, app: Any) -> None:
        self.app = app


async def asleep(request: Any) -> List[Dict[str, Any]]:
    from src.api.asleep_brief import asleep_brief  # noqa: PLC0415

    return await asleep_brief()


async def wake(request: Any, session_uuid: str) -> Dict[str, Any]:
    from src.api.session_sleep_routes import wake_session  # noqa: PLC0415

    result = await wake_session(request, session_uuid, None)
    logger.info("cplug_session_woken", session_uuid=session_uuid, status=result.status)
    return {"status": result.status, "detail": getattr(result, "detail", None), "code": result.code}


async def start(request: Any, project_id: int) -> str:
    from src.api.session_crud_routes import create_session  # noqa: PLC0415
    from src.models import CreateSessionRequest  # noqa: PLC0415

    project = capabilities.Projects().get(project_id)
    if project is None or not project.get("path"):
        raise LookupError(f"no project {project_id} with a folder")
    body = CreateSessionRequest(working_dir=project["path"], auto_start_claude=True, copy_templates=False,
                                project_name=project["name"], label=project["name"],
                                agent_type=project.get("default_launch_profile") or None)
    session = await create_session(request, body)
    logger.info("cplug_session_started", project=project_id, session_id=session.id)
    return session.id


async def start_in_folder(request: Any, working_dir: str, label: str, opening_prompt: str) -> str:
    from pathlib import Path  # noqa: PLC0415

    from src.api.session_crud_routes import create_session  # noqa: PLC0415
    from src.core.swarm.slugs import slugify  # noqa: PLC0415
    from src.models import CreateSessionRequest  # noqa: PLC0415

    if not Path(working_dir).is_dir():
        raise LookupError(f"no folder {working_dir}")
    body = CreateSessionRequest(working_dir=working_dir, auto_start_claude=True, copy_templates=False, project_name=slugify(label), label=label,
                                opening_prompt=opening_prompt)
    session = await create_session(request, body)
    logger.info("cplug_session_started_in_folder", session_id=session.id, label=label)
    return session.id


BOOT_WAIT_S = 60.0


async def resume(request: Any, session_uuid: str, wrapper: str) -> Dict[str, Any]:
    from src.api.recreate_action import recreate_by_uuid  # noqa: PLC0415

    started = await recreate_by_uuid(session_uuid, wrapper, get_manager=lambda: request.app.state.session_manager)
    logger.info("cplug_session_resumed", session_uuid=session_uuid, status=started.status)
    return {"status": started.status, "session_uuid": started.session_uuid, "session_name": started.session_name,
            "session_id": started.session_id, "detail": started.detail or ""}


async def booted(request: Any, timeout: float = BOOT_WAIT_S) -> None:
    task = request.app.state.session_manager._boot_readopt_task
    if task is None or task.done():
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout)
    except asyncio.TimeoutError:
        logger.warning("cplug_boot_readopt_wait_timed_out", seconds=timeout)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("cplug_boot_readopt_failed", error_type=type(exc).__name__, error=str(exc)[:200])
