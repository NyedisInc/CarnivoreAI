
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from src.cplugs.huddle import files, service, task_files
from src.cplugs.huddle.rules import TaskManagerError
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError
from src.cplugs.sdk.local_files import read_local_file

FIELD = "file_paths"
SCHEMA: Dict[str, Any] = {FIELD: {
    "type": "array", "maxItems": files.MAX_PER_REPLY, "items": {"type": "string"},
    "description": ("Files to attach, by ABSOLUTE path on this computer (a session running here only; refused for a token). Each is copied "
                    "into the task's folder and shows on the thread like the owner's pasted files: an image (png, jpg, gif, webp) up to 10 MB, "
                    f"any other file up to 50 MB, at most {files.MAX_PER_REPLY}.")}}


def _store(ctx: CplugContext, caller: AgentCaller, item_id: int, paths: List[Any]) -> str:
    service.store(ctx).item(item_id)
    loaded = [read_local_file(caller, path, argument=FIELD) for path in paths]
    target = task_files.folder_for(ctx, item_id, task_files.PASTES)
    saved = [files.save(ctx.storage, item_id, name, data, folder=target) for data, name in loaded]
    folders = [target] if target is not None else []
    return files.parts_of([files.describe(ctx.storage, item_id, s["id"], folders) for s in saved])


async def parts_for(ctx: CplugContext, caller: AgentCaller, item_id: int, value: Any) -> str:
    if value is None:
        return ""
    if caller.from_token:
        raise ToolError(f"{FIELD} names files on this computer, so only a session running here may pass it")
    if not isinstance(value, list) or not value or len(value) > files.MAX_PER_REPLY:
        raise ToolError(f"{FIELD} must be a list of 1 to {files.MAX_PER_REPLY} absolute paths")
    try:
        return await asyncio.to_thread(_store, ctx, caller, item_id, value)
    except TaskManagerError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc
    except OSError as exc:
        raise ToolError(f"{FIELD}: a file could not be stored ({type(exc).__name__})") from exc
