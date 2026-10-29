from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException

from src.core.automations import session_tree
from src.api.error_response import api_error

logger = structlog.get_logger()

GROUP_BY_SESSION = "session"


async def resolve_session(request: Any, text: str, rows: List[Dict[str, Any]]) -> Tuple[str, Optional[int]]:
    known = next((r for r in rows if r.get("session_uuid") == text), None)
    if known is not None:
        return text, known.get("project_id")
    from src.core.mcp.common import ToolError  # noqa: PLC0415
    from src.core.mcp.protocol import BatchView  # noqa: PLC0415
    from src.core.mcp.session_target import STORED, TargetResolver  # noqa: PLC0415

    manager = getattr(request.app.state, "session_manager", None)
    if manager is None:
        raise HTTPException(503, detail={"code": "sessions_unavailable"})
    resolver = TargetResolver(BatchView(manager, request.app))
    try:
        target = await resolver.resolve({"target": text}, reach=STORED, tool="automations_list")
        uuid = await resolver.uuid_of(target)
    except ToolError as exc:
        raise api_error(404, "session_not_found", exc) from exc
    row = next((r for r in rows if r.get("session_uuid") == uuid), None)
    project_id = row.get("project_id") if row else (target.row or {}).get("project_id")
    return uuid, project_id


async def list_view(request: Any, store: Any, with_last_run: Any, project_id: int, session: Optional[str], enabled: Optional[bool],
                    target_kind: Optional[str], group_by: Optional[str]) -> Dict[str, Any]:
    from src.core.automations import models as m  # noqa: PLC0415
    from src.core.db import DatastoreUnreadableError  # noqa: PLC0415

    if group_by not in (None, GROUP_BY_SESSION):
        raise HTTPException(422, detail={"code": "group_by_invalid", "message": f"group_by can only be {GROUP_BY_SESSION!r}"})
    if target_kind is not None and target_kind not in m.TARGET_KINDS:
        raise HTTPException(422, detail={"code": "target_kind_invalid", "message": f"target_kind is one of: {', '.join(sorted(m.TARGET_KINDS))}"})
    inputs: Dict[str, List[Dict[str, Any]]] = {"projects": [], "sessions": []}
    if session is not None or group_by:
        try:
            inputs = await asyncio.to_thread(session_tree.read_inputs)
        except (OSError, DatastoreUnreadableError) as exc:
            logger.warning("automations.list_view.datastore_unreadable", error=type(exc).__name__)
            raise HTTPException(503, detail={"code": "datastore_unreadable"}) from exc
    wanted: Optional[Tuple[str, Optional[int]]] = None
    if session is not None:
        wanted = await resolve_session(request, session, inputs["sessions"])
    rows = await asyncio.to_thread(store.list_all, project_id or None)
    rows = [r for r in rows if (enabled is None or r["enabled"] == enabled) and (target_kind is None or r["target"].get("kind") == target_kind)
            and (wanted is None or session_tree.matches_session(r, *wanted))]
    full = [await with_last_run(store, r) for r in rows]
    if group_by != GROUP_BY_SESSION:
        return {"automations": full}
    tree = session_tree.build_tree(inputs["projects"], inputs["sessions"], full)
    narrowed = project_id or enabled is not None or target_kind is not None or wanted is not None
    return {"group_by": GROUP_BY_SESSION, "tree": session_tree.prune_empty(tree) if narrowed else tree}
