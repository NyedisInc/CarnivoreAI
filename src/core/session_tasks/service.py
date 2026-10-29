
from __future__ import annotations

import asyncio
from typing import Any, List, Optional

import structlog

from src.core.agent_families import DEFAULT_FAMILY
from src.core.session_tasks.reader import TaskReader, TranscriptUnreadable, count
from src.core.session_token_usage.claude_reader import locate_transcript
from src.core.session_transcript_presence import CONVERSATION_ABSENT, CONVERSATION_PRESENT
from src.models.session_tasks import AllSessionTasks, SessionTasks

logger = structlog.get_logger(__name__)


def label_of(info: Any) -> str:
    return info.label or info.tmux_session or info.session.id


async def tasks_for(info: Any, reader: TaskReader) -> SessionTasks:
    base = {"session_id": info.session.id, "label": label_of(info)}
    family: Optional[str] = getattr(info, "agent_family", None)
    if family is not None and family != DEFAULT_FAMILY:
        return SessionTasks(state="unsupported", **base)
    if not info.claude_session_uuid:
        return SessionTasks(state="empty", **base)
    where = await asyncio.to_thread(
        locate_transcript, info.claude_session_uuid, working_dir=info.session.working_dir)
    if where.outcome == CONVERSATION_ABSENT:
        return SessionTasks(state="empty", **base)
    if where.outcome != CONVERSATION_PRESENT or where.path is None:
        return SessionTasks(state="unknown", **base)
    try:
        items = await asyncio.to_thread(reader.read, where.path)
    except TranscriptUnreadable as exc:
        if not exc.repeat:
            logger.warning("session_tasks_unreadable", session=info.session.id, error=str(exc))
        return SessionTasks(state="unknown", **base)
    return SessionTasks(state="ok" if items else "empty", tasks=items, counts=count(items), **base)


async def all_tasks(manager: Any, reader: TaskReader) -> AllSessionTasks:
    infos: List[Any] = await manager.list_session_infos()
    rows = await asyncio.gather(*(tasks_for(info, reader) for info in infos))
    return AllSessionTasks(sessions=[row for row in rows if row.state == "ok"])
