
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict, Tuple

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool

from src.api.error_response import api_error, soft_failure
from src.api.auth import require_auth
from src.core.db import DatastoreUnreadableError, db_path_for
from src.core.db_reuse.core_read import lend_pooled_or_raise
from src.core.hosts import store
from src.core.hosts.probe import probe_host
from src.core.hosts.ssh_exec import SshArgumentError, SshDestination
from src.models.hosts import (
    CreateHostRequest,
    HostDeletedResponse,
    HostModel,
    HostsResponse,
    LinkComputerRequest,
    UpdateHostRequest,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/hosts", tags=["hosts"])

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"

_UNAVAILABLE = (DatastoreUnreadableError, store.HostsUnavailable, sqlite3.DatabaseError, OSError)


def _db_path():
    from src.config import settings

    return db_path_for(settings.get_state_dir())


def to_model(host: store.Host, counts: Dict[str, int]) -> HostModel:
    return HostModel(
        key=host.key, label=host.label, local=host.is_local, ssh_target=host.ssh_target,
        ssh_port=host.ssh_port, socket=host.socket, enabled=host.enabled,
        session_count=counts.get(host.key, 0), probe_state=host.probe_state,
        probe_detail=host.probe_detail, probed_at=host.probed_at, tmux_path=host.tmux_path,
        tmux_version=host.tmux_version, login_path=host.login_path,
        agent_paths=host.agent_paths, login_shell=host.login_shell,
        machine_id=host.machine_id, remote_carnivore=host.remote_carnivore,
        computer_install_id=host.computer_install_id, created_at=host.created_at, updated_at=host.updated_at,
    )


PEER_NOT_CONNECTED = "peer_not_connected"
PEER_REFUSES_HOSTING = "peer_refuses_hosting"


def overlay_peers(conn: sqlite3.Connection, hosts: list) -> list:
    from dataclasses import replace

    from src.core.federation import peer_hosts
    from src.core.pack.machines import runtime

    peers = {p.key: p for p in peer_hosts.list_peers(conn)} if any(h.kind == "peer" for h in hosts) else {}
    out = []
    for host in hosts:
        peer = peers.get(host.key) if host.kind == "peer" else None
        if peer is None:
            out.append(host)
        elif peer.peer_state != "connected":
            out.append(replace(host, enabled=False, probe_state="refused", probe_detail=PEER_NOT_CONNECTED))
        elif runtime.peer_restriction(peer.peer_install_id, "may_host_agents") is False:
            out.append(replace(host, enabled=False, probe_state="refused", probe_detail=PEER_REFUSES_HOSTING))
        else:
            out.append(replace(host, enabled=True, probe_state="ok", probe_detail=None))
    return out


def _run(operation: Callable, *args: Any, **kwargs: Any) -> Tuple[Any, Dict[str, int]]:
    with closing(lend_pooled_or_raise(_db_path())) as conn:
        result = operation(conn, *args, **kwargs)
        return result, store.session_counts(conn)


async def _call(operation: Callable, *args: Any, **kwargs: Any) -> Tuple[Any, Dict[str, int]]:
    try:
        return await run_in_threadpool(_run, operation, *args, **kwargs)
    except store.HostInvalid as exc:
        raise api_error(400, exc.code, exc, extra={"reason": str(exc)}) from exc
    except store.HostNotFound as exc:
        raise api_error(404, "host_not_found", exc) from exc
    except store.HostKeyTaken as exc:
        raise api_error(409, "host_key_taken", exc) from exc
    except store.HostLocalFixed as exc:
        raise api_error(409, "host_local_fixed", exc) from exc
    except store.HostInUse as exc:
        raise api_error(409, "host_in_use", exc) from exc
    except store.ComputerUnknown as exc:
        raise api_error(404, "computer_not_found", exc) from exc
    except _UNAVAILABLE as exc:
        raise api_error(503, "hosts_unavailable", exc) from exc


async def _forget_connection(request: Request, key: str) -> None:
    manager = getattr(request.app.state, "session_manager", None)
    if manager is not None:
        await manager.hosts.forget(key)


@router.get("", response_model=HostsResponse, dependencies=[Depends(require_auth)])
async def list_hosts() -> HostsResponse:
    """Every host, this machine first, or an explicit CANNOT DETERMINE.

    Description: 200 in both outcomes, like the Layouts read, so a client
      can tell "no hosts" from "could not read the hosts".
    Output: HostsResponse.
    Example: GET /api/v1/hosts
    """
    try:
        hosts, counts = await run_in_threadpool(_run, lambda conn: overlay_peers(conn, store.list_hosts(conn)))
    except _UNAVAILABLE as exc:
        return HostsResponse(status=STATUS_UNAVAILABLE, detail=soft_failure("datastore_unavailable", exc, step="list_hosts"))
    return HostsResponse(status=STATUS_OK, hosts=[to_model(h, counts) for h in hosts])


@router.post("", response_model=HostModel, dependencies=[Depends(require_auth)])
async def add_host(body: CreateHostRequest) -> HostModel:
    """Add a machine by its ssh target. Stored with ``probe_state`` 'never'.

    Description: the key is generated server side (Alex (Adoom666),
      2026-09-28), never supplied by the caller; the response carries it.
    Raises: HTTPException 400 (a field is invalid), 409 (key generation
      exhausted its retries), 503.
    Example: POST /api/v1/hosts {"label": "Studio", "ssh_target": "studio"}
    """
    host, counts = await _call(store.create_host, label=body.label,
                               ssh_target=body.ssh_target, ssh_port=body.ssh_port,
                               socket=body.socket)
    return to_model(host, counts)


@router.get("/{key}", response_model=HostModel, dependencies=[Depends(require_auth)])
async def get_host(key: str) -> HostModel:
    """One host. Raises: HTTPException 404, 503. Example: GET /api/v1/hosts/local"""
    host, counts = await _call(store.get_host, key)
    return to_model(host, counts)


@router.patch("/{key}", response_model=HostModel, dependencies=[Depends(require_auth)])
async def update_host(key: str, body: UpdateHostRequest, request: Request) -> HostModel:
    """Change a remote host's label, enabled flag or socket.

    Raises: HTTPException 400, 404, 409 (this machine, or a socket change
      while sessions run there), 503.
    Example: PATCH /api/v1/hosts/studio {"label": "Studio (studio)"}
    """
    host, counts = await _call(store.update_host, key, label=body.label,
                               enabled=body.enabled, socket=body.socket)
    if body.enabled is not None or body.socket is not None:
        await _forget_connection(request, key)
    return to_model(host, counts)


@router.delete("/{key}", response_model=HostDeletedResponse,
               dependencies=[Depends(require_auth)])
async def delete_host(key: str, request: Request) -> HostDeletedResponse:
    """Remove a host no sessions row names. Nothing on that machine is touched.

    Raises: HTTPException 404, 409 (this machine, or sessions still name it), 503.
    Example: DELETE /api/v1/hosts/studio
    """
    await _call(store.delete_host, key)
    await _forget_connection(request, key)
    return HostDeletedResponse(key=key)


@router.post("/{key}/probe", response_model=HostModel, dependencies=[Depends(require_auth)])
async def probe(key: str, request: Request) -> HostModel:
    """Probe a remote host over its own ssh connection and store what it found.

    Description: one ``ssh -G`` on this machine, then one connection that
      measures the login shell, tmux, the agents, the machine id and
      whether the far box runs its own Carnivore. Every outcome, an
      unreachable host or a changed host key included, is stored and
      answered as ``probe_state``; the HTTP status only speaks for the
      request itself.
    Raises: HTTPException 404, 409 (this machine), 400 (a stored target or
      socket the transport refuses), 503.
    Example: POST /api/v1/hosts/studio/probe
    """
    host, _ = await _call(store.get_host, key)
    if host.is_local:
        raise api_error(409, "host_local_fixed")
    try:
        dest = SshDestination(host.ssh_target or "", host.ssh_port)
    except SshArgumentError as exc:
        raise api_error(400, "host_target_invalid", exc, extra={"reason": str(exc)}) from exc
    try:
        result = await probe_host(dest, socket=host.socket or store.DEFAULT_REMOTE_SOCKET)
    except store.HostInvalid as exc:
        raise api_error(400, exc.code, exc, extra={"reason": str(exc)}) from exc
    logger.info("host_probed", host=key, verdict=result.verdict, elapsed_ms=result.elapsed_ms)
    written, counts = await _call(store.record_probe, key, result.host_columns())
    await _forget_connection(request, key)
    return to_model(written, counts)


@router.put("/{key}/computer", response_model=HostModel, dependencies=[Depends(require_auth)])
async def link_computer(key: str, body: LinkComputerRequest) -> HostModel:
    """Say which Pack computer an ssh host belongs to; null clears the link (#2061).

    Description: the link is the owner's word, stored on the host row, so the Pack page joins the host to the computer
      by it first and by the ssh target text only as a fallback. The ``computers`` topic is told, since the page reads
      the merged roster from that push.
    Raises: HTTPException 404 (no such host, or no such computer), 409 (this machine or a peer row), 503.
    Example: PUT /api/v1/hosts/studio/computer {"computer_install_id": "iid-studio"}
    """
    host, counts = await _call(store.link_computer, key, body.computer_install_id)
    from src.core import resource_push

    resource_push.notify("computers")
    return to_model(host, counts)
