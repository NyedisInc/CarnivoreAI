
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Awaitable, Callable, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.core.pack.jobs import policy as policy_mod
from src.core.pack.jobs.place import PlaceView, drop_reason
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobError
from src.models.projects import AddReplicaRequest

logger = structlog.get_logger()

AddFn = Callable[[str, AddReplicaRequest], Awaitable[object]]
HasFn = Callable[[str, str], bool]


def _default_has(project_uid: str, install_id: str) -> bool:
    from src.api import projects_service
    from src.config import settings
    from src.core.pack.identity import replicas

    with closing(projects_service.open_db_or_503(settings)) as conn:
        return any(r["install_id"] == install_id for r in replicas.list_replicas(conn, project_uid))


def _default_add() -> AddFn:
    from src.api import project_replica_routes

    return project_replica_routes.add_project_replica


async def ensure(project_name: str, project_uid: str, install_id: str, *, store: JobStore, add: Optional[AddFn] = None,
                 has: Optional[HasFn] = None) -> bool:
    if await asyncio.to_thread(has or _default_has, project_uid, install_id):
        return False
    kept_root = policy_mod.detached_root(store, project_uid, install_id)
    try:
        view = await (add or _default_add())(project_name, AddReplicaRequest(machine=install_id, root=kept_root, transport="carried", auto=True))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if kept_root:
            policy_mod.forget_detached_root(store, project_uid, install_id)
        raise JobError(str(detail.get("code") or f"http_{exc.status_code}"), str(detail.get("detail") or exc.detail), exc.status_code) from exc
    answer = (view or {}).get("replica") if isinstance(view, dict) else None
    if not (isinstance(answer, dict) and answer.get("folder_made") is False):
        policy_mod.record_auto_replica(store, project_uid, install_id)
    if kept_root:
        policy_mod.forget_detached_root(store, project_uid, install_id)
    logger.info("pack_jobs_auto_replica", project_uid=project_uid, machine=install_id)
    return True


async def ensure_all(project_name: str, project_uid: str, *, store: JobStore, view: PlaceView, policy: policy_mod.Policy,
                     add: Optional[AddFn] = None, has: Optional[HasFn] = None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    peers: List = [p for p in view.peers if p.usable and not p.install_id.startswith("ssh:") and drop_reason(p, policy, view) is None]
    for peer in peers:
        if not policy_mod.get(store, project_uid).auto_delegate:
            break
        try:
            made = await ensure(project_name, project_uid, peer.install_id, store=store, add=add, has=has)
        except JobError as exc:
            out[peer.install_id] = exc.code
        else:
            out[peer.install_id] = "created" if made else "present"
    return out
