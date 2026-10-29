"""API routes for remote tmux hosts (issue #162, slice S1): add, list, edit, remove.

Deliberately thin, in the ``layouts_routes.py`` pattern: request and
response shape, auth, error translation and the connection dance. Every rule
about what a host IS lives in ``src/core/hosts/store.py``; the design is
``docs/remote-hosts.md``. EVERY USER ACTION IS ONE ROUTE (the API-first
rule), so the MCP wrapper (#152) is one thin adapter per route:

A probe's verdict is data, never an HTTP error: an unreachable host is a
200 whose ``probe_state`` names why (``src/core/hosts/probe.py``). The
connect and attachable routes arrive with later slices.

ERRORS carry ``{"code", "detail"}`` so a client branches on the code, never
on prose: 400 ``host_key_invalid`` / ``host_key_reserved`` /
``host_label_invalid`` / ``host_target_invalid`` / ``host_port_invalid`` /
``host_socket_invalid`` / ``host_socket_reserved`` / ``host_enabled_invalid``;
404 ``host_not_found`` / ``computer_not_found``; 409 ``host_key_taken`` / ``host_local_fixed`` /
``host_in_use``; 503 ``hosts_unavailable`` when the datastore could not
answer.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.core.db import DatastoreUnreadableError, connect, db_path_for
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

# could not
_UNAVAILABLE = (DatastoreUnreadableError, store.HostsUnavailable, sqlite3.DatabaseError, OSError)


def _db_path():
    from src.config import settings

    return db_path_for(settings.get_state_dir())


def _error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


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
    with closing(connect(_db_path(), create=False)) as conn:
        result = operation(conn, *args, **kwargs)
        return result, store.session_counts(conn)


async def _call(operation: Callable, *args: Any, **kwargs: Any) -> Tuple[Any, Dict[str, int]]:
    try:
        return await run_in_threadpool(_run, operation, *args, **kwargs)
    except store.HostInvalid as exc:
        raise _error(400, exc.code, str(exc))
    except store.HostNotFound as exc:
        raise _error(404, "host_not_found", str(exc))
    except store.HostKeyTaken as exc:
        raise _error(409, "host_key_taken", str(exc))
    except store.HostLocalFixed as exc:
        raise _error(409, "host_local_fixed", str(exc))
    except store.HostInUse as exc:
        raise _error(409, "host_in_use", str(exc))
    except store.ComputerUnknown as exc:
        raise _error(404, "computer_not_found", str(exc))
    except _UNAVAILABLE as exc:
        logger.warning("hosts_unavailable", error=str(exc), error_type=type(exc).__name__)
        raise _error(503, "hosts_unavailable", str(exc))


@router.get("", response_model=HostsResponse, dependencies=[Depends(require_auth)])
async def list_hosts() -> HostsResponse:
    try:
        hosts, counts = await run_in_threadpool(_run, lambda conn: overlay_peers(conn, store.list_hosts(conn)))
    except _UNAVAILABLE as exc:
        logger.info("hosts_unavailable", reason=str(exc))
        return HostsResponse(status=STATUS_UNAVAILABLE, detail=str(exc))
    return HostsResponse(status=STATUS_OK, hosts=[to_model(h, counts) for h in hosts])


@router.post("", response_model=HostModel, dependencies=[Depends(require_auth)])
async def add_host(body: CreateHostRequest) -> HostModel:
    """Add a machine by its ssh target. Stored with ``probe_state`` 'never'.
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
async def update_host(key: str, body: UpdateHostRequest) -> HostModel:
    """Change a remote host's label, enabled flag or socket.
    """
    host, counts = await _call(store.update_host, key, label=body.label,
                               enabled=body.enabled, socket=body.socket)
    return to_model(host, counts)


@router.delete("/{key}", response_model=HostDeletedResponse,
               dependencies=[Depends(require_auth)])
async def delete_host(key: str) -> HostDeletedResponse:
    """Remove a host no sessions row names. Nothing on that machine is touched.
    """
    await _call(store.delete_host, key)
    return HostDeletedResponse(key=key)


@router.post("/{key}/probe", response_model=HostModel, dependencies=[Depends(require_auth)])
async def probe(key: str) -> HostModel:
    """Probe a remote host over its own ssh connection and store what it found.
    """
    host, _ = await _call(store.get_host, key)
    if host.is_local:
        raise _error(409, "host_local_fixed", "'local' is this machine; it is never probed over ssh")
    try:
        dest = SshDestination(host.ssh_target or "", host.ssh_port)
    except SshArgumentError as exc:
        raise _error(400, "host_target_invalid", str(exc))
    try:
        result = await probe_host(dest, socket=host.socket or store.DEFAULT_REMOTE_SOCKET)
    except store.HostInvalid as exc:
        raise _error(400, exc.code, str(exc))
    logger.info("host_probed", host=key, verdict=result.verdict, elapsed_ms=result.elapsed_ms)
    written, counts = await _call(store.record_probe, key, result.host_columns())
    return to_model(written, counts)


@router.put("/{key}/computer", response_model=HostModel, dependencies=[Depends(require_auth)])
async def link_computer(key: str, body: LinkComputerRequest) -> HostModel:
    """Say which Pack computer an ssh host belongs to; null clears the link (#2061).
    """
    host, counts = await _call(store.link_computer, key, body.computer_install_id)
    from src.core import resource_push

    resource_push.notify("computers")
    return to_model(host, counts)
