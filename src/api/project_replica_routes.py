
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.api import peer_auth, projects_service
from src.api.auth import require_auth
from src.config import settings
from src.core.computers import direction
from src.core.db import get_meta, transaction
from src.core.db_models import META_INSTALL_ID
from src.core.federation import peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.account_switch.launch_env import _config_path
from src.core.pack.identity import home, replicas
from src.core.pack.move import account
from src.core.pack.transport import bundles
from src.core.pack.trust_carry import imports, store as trust_store
from src.core.pack.trust_carry import wire as trust_wire
from src.models.projects import AddReplicaRequest, SetAirGapRequest

logger = structlog.get_logger()
router = APIRouter()

REPLICA_PATH = "/federation/pack/replica"
PEER_TIMEOUT_SECONDS = 20.0


def _project(conn: Any, name: str) -> Dict[str, Any]:
    return projects_service.resolve_target(conn, name)


def _require_home(conn: Any, project: Dict[str, Any]) -> None:
    state = project.get("pack_state")
    if state == home.MOVED_AWAY:
        raise home.ProjectMovedAway(project["display_name"], home.machine_label(conn, project.get("moved_to_install_id")), project["root"])
    if state == home.REPLICA:
        raise HTTPException(409, {"code": "not_project_home", "detail": "this machine holds a replica; change replicas on the project's home"})


def find_peer(machine: str) -> peer_hosts.PeerRow:
    with closing(peer_auth.open_db()) as conn:
        peers = peer_hosts.list_peers(conn)
    wanted = machine.strip().lower()
    for peer in peers:
        if wanted in (peer.key.lower(), str(peer.label).lower(), peer.peer_install_id.lower()):
            return peer
    raise HTTPException(404, {"code": "unknown_machine", "detail": f"no paired computer named {machine!r}"})


async def call_peer(peer: peer_hosts.PeerRow, method: str, path: str, body: Any = None) -> Any:
    links = peer_links.LINKS
    client = links.client(peer.peer_install_id) if links is not None else None
    if client is None:
        raise HTTPException(502, {"code": "machine_unreachable", "detail": f"{peer.label} is not connected right now"})
    try:
        reply = await asyncio.wait_for(client.request(method, path, json=body), PEER_TIMEOUT_SECONDS)
    except (PeerUnreachable, PeerRefused, asyncio.TimeoutError) as exc:
        raise HTTPException(502, {"code": "machine_unreachable", "detail": f"{peer.label} did not answer ({type(exc).__name__})"}) from exc
    try:
        data = reply.json() if reply.status_code == 200 else None
    except ValueError:
        data = None
    if reply.status_code != 200:
        code = "replica_refused"
        try:
            detail = reply.json().get("detail")
            code = detail.get("code", code) if isinstance(detail, dict) else code
        except (ValueError, AttributeError):
            detail = None
        raise HTTPException(502, {"code": code, "detail": f"{peer.label} refused ({reply.status_code})", "peer_detail": detail})
    return data or {}


def _view(conn: Any, project: Dict[str, Any]) -> Dict[str, Any]:
    return {"project_uid": project["uid"], "name": project["display_name"], "pack_state": project["pack_state"],
            "home_install_id": project.get("home_install_id"), "air_gap": bool(project.get("air_gap")),
            "replicas": replicas.list_replicas(conn, project["uid"]) if project["pack_state"] == home.HOME else []}


@router.get("/projects/{project_name}/replicas", dependencies=[Depends(require_auth)])
async def list_project_replicas(project_name: str) -> Dict[str, Any]:
    """The project's uid, its home state and the machines holding an active replica of it.

    Inputs: project_name (str, URL display name). Output: {project_uid, name, pack_state, home_install_id, air_gap, replicas[]}.
    Raises: HTTPException 404 unknown project, 409 ambiguous name, 503 datastore unreachable.
    Example: GET /api/v1/projects/ledgerbot/replicas
    """
    def read() -> Dict[str, Any]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            return _view(conn, _project(conn, project_name))

    return await run_in_threadpool(read)


@router.post("/projects/{project_name}/replicas", dependencies=[Depends(require_auth)])
async def add_project_replica(project_name: str, body: AddReplicaRequest) -> Dict[str, Any]:
    """Make an ACTIVE replica of this project on a paired machine, against the same uid.

    Description: the machine registers the project under the home's uid (its folder created, or an existing project at
      ``root`` adopted), then this home records the replica. Agents and sessions then run on both at the same time.
    Inputs: project_name (str); body (AddReplicaRequest: machine, root?, transport).
    Output: the replica view (as GET) plus ``replica`` (the machine's answer).
    Raises: HTTPException 404 unknown project or machine, 409 ``project_moved_away`` or ``not_project_home``, 502 the machine
      is unreachable or refused (``machine_unreachable``, or its own code such as ``project_name_taken``).
    Example: POST /api/v1/projects/ledgerbot/replicas {"machine": "hosta"}
    """
    def read() -> Dict[str, Any]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            project = _project(conn, project_name)
            _require_home(conn, project)
            company = conn.execute("SELECT uid, name FROM companies WHERE id = ?", (project.get("company_id"),)).fetchone() \
                if project.get("company_id") is not None else None
            profiles = [account.session_profile_dir(_config_path(), r[0]) for r in
                        conn.execute("SELECT session_uuid FROM sessions WHERE project_id = ?", (project["id"],)).fetchall()]
            return {"project": project, "profiles": profiles, "install_id": get_meta(conn, META_INSTALL_ID),
                    "company_uid": company[0] if company else None, "company_name": company[1] if company else None}

    found = await run_in_threadpool(read)
    project, peer = found["project"], await run_in_threadpool(find_peer, body.machine)
    if direction.contained(peer.peer_install_id):
        raise HTTPException(409, {"code": direction.REFUSAL_CODE, "detail": f"{peer.label} is set to one way and holds no replicas"})
    answer = await call_peer(peer, "POST", REPLICA_PATH, {
        "project_uid": project["uid"], "name": project["display_name"], "root": body.root,
        "company_uid": found["company_uid"], "company_name": found["company_name"], "transport": body.transport,
        **trust_wire.source_trusted_field(peer.peer_install_id, await run_in_threadpool(trust_store.project_trusted, project["root"], found["profiles"])),
        **trust_wire.source_imports_field(peer.peer_install_id, await run_in_threadpool(imports.source_imports_ok, project["root"], found["profiles"]))})

    def write() -> Dict[str, Any]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            replicas.record_replica(conn, project["uid"], peer.peer_install_id, answer.get("root") or body.root, body.transport)
            home.notify_changed()
            view = {**_view(conn, _project(conn, project_name)), "replica": answer}
        _sync_proxy_scope(peer.peer_install_id)
        return view

    logger.info("project_replica_added", project_uid=project["uid"], machine=peer.key)
    view = await run_in_threadpool(write)
    from src.api import project_transport_routes

    if await run_in_threadpool(bundles.is_repo, project["root"]):
        view["code"] = await project_transport_routes.carry_to(project, peer.peer_install_id, str(peer.label), False)
    return view


@router.delete("/projects/{project_name}/replicas/{machine}", dependencies=[Depends(require_auth)])
async def remove_project_replica(project_name: str, machine: str) -> Dict[str, Any]:
    """Stop a machine being a replica of this project: it keeps its folder and project as an ordinary one under a new uid.

    Inputs: project_name (str); machine (str: label, host key or install id). Output: the replica view (as GET).
    Raises: HTTPException 404 unknown project, machine or replica, 409 ``project_moved_away`` or ``not_project_home``,
      502 the machine is unreachable (the replica row is kept until it has been told).
    Example: DELETE /api/v1/projects/ledgerbot/replicas/hosta
    """
    def read() -> Dict[str, Any]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            project = _project(conn, project_name)
            _require_home(conn, project)
            return project

    project, peer = await run_in_threadpool(read), await run_in_threadpool(find_peer, machine)
    known = await run_in_threadpool(lambda: _has_replica(project["uid"], peer.peer_install_id))
    if not known:
        raise HTTPException(404, {"code": "unknown_replica", "detail": f"{peer.label} holds no replica of {project['display_name']!r}"})
    await call_peer(peer, "DELETE", f"{REPLICA_PATH}/{project['uid']}")

    def write() -> Dict[str, Any]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            replicas.forget_replica(conn, project["uid"], peer.peer_install_id)
            home.notify_changed()
            view = _view(conn, _project(conn, project_name))
        _sync_proxy_scope(peer.peer_install_id)
        return view

    return await run_in_threadpool(write)


def _sync_proxy_scope(peer_install_id: str) -> None:
    from src.core.pack.machines import runtime

    wired = runtime.wiring()
    if wired is not None:
        wired.sync_scopes(peer_install_id)


def _has_replica(project_uid: str, install_id: str) -> bool:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        return any(r["install_id"] == install_id for r in replicas.list_replicas(conn, project_uid))


@router.put("/projects/{project_name}/air-gap", dependencies=[Depends(require_auth)])
async def set_project_air_gap(project_name: str, body: SetAirGapRequest) -> Dict[str, Any]:
    """Set the project's air-gap: true means Carnivore never contacts GitHub for it (P3's transport reads this).

    Inputs: project_name (str); body (SetAirGapRequest). Output: the replica view (as GET).
    Raises: HTTPException 404 unknown project, 409 ambiguous name, 503 datastore unreachable.
    Example: PUT /api/v1/projects/ledgerbot/air-gap {"air_gap": true}
    """
    def write() -> Dict[str, Any]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            project = _project(conn, project_name)
            with transaction(conn):
                conn.execute("UPDATE projects SET air_gap = ? WHERE id = ?", (1 if body.air_gap else 0, project["id"]))
            home.notify_changed()
            return _view(conn, _project(conn, project_name))

    return await run_in_threadpool(write)
