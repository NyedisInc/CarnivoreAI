
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from typing import Any, Dict, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.core.computers import add_over_ssh, add_preview, join_job, membership, runtime, store, terminal_helper, view
from src.core.computers.invites import Invite, MemberRefused, TooManyInvites
from src.core.computers.join_link import build_link
from src.core.federation import grants, peer_hosts, peer_links, peer_sockets
from src.core.federation.pairing import KeyedWindows
from src.core.hosts import ssh_exec

logger = structlog.get_logger()

router = APIRouter(prefix="/computers", tags=["computers"], dependencies=[Depends(require_auth)])

_INVITE_WINDOW = KeyedWindows(6, 60.0)
_PREVIEW_WINDOW = KeyedWindows(10, 60.0)
_JOIN_ERRORS = {"bad_request": 422, "bad_link": 422, "already_joined": 409, "undetermined": 409, "unavailable": 503}


class JoinBody(BaseModel):
    """Body of ``POST /computers/join``: exactly one of ``code`` and ``link``; ``candidate_fid`` picks among several packs."""

    model_config = ConfigDict(extra="forbid")

    code: Optional[str] = Field(default=None, max_length=16, repr=False)
    link: Optional[str] = Field(default=None, max_length=512, repr=False)
    candidate_fid: Optional[str] = Field(default=None, max_length=64)


class AddPreviewBody(BaseModel):
    """Body of ``POST /computers/add/preview``: the ssh target (alias or ``user@host``) and an optional port."""

    model_config = ConfigDict(extra="forbid")

    ssh_target: str = Field(max_length=ssh_exec.TARGET_MAX)
    ssh_port: Optional[int] = Field(default=None, ge=1, le=65535)


class AddBody(AddPreviewBody):

    host_key_sha256: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/=]{20,64}$")
    label: Optional[str] = Field(default=None, max_length=64)


class DirectionBody(BaseModel):
    """Body of ``PUT /computers/peers/{install_id}/direction``."""

    model_config = ConfigDict(extra="forbid")

    direction: Literal["both", "one_way"]


def _error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def _rt() -> runtime.ComputersRuntime:
    rt = runtime.active()
    if rt is None:
        raise _error(503, "computers_unavailable", "the computers link is not running")
    return rt


async def _inviter() -> runtime.ComputersRuntime:
    rt = _rt()
    await asyncio.to_thread(rt.refresh_flags)
    if rt.joined:
        raise _error(409, "joined_computer", "this computer joined a pack; it adds no computers")
    if not rt.complete or rt.invites is None or rt.join_server is None:
        raise _error(409, "setup_incomplete", "finish setting up this computer first")
    return rt


def _links() -> Any:
    return peer_links.LINKS


def _invite_json(rt: runtime.ComputersRuntime, inv: Invite) -> Dict[str, Any]:
    assert rt.identity is not None
    return {"id": inv.id, "code": inv.code, "link": build_link(rt.addresses, rt.link_port, rt.identity.cert.der, inv),
            "expires_at": view.iso(inv.expires_at), "attempts_left": inv.attempts_left}


@router.get("")
async def get_computers(request: Request) -> Dict[str, Any]:
    """Every computer, this one's role and link state, and the live invites without their codes. Output: ``ComputersView``."""
    rt = _rt()
    try:
        return await asyncio.to_thread(view.build_view, rt, _links())
    except sqlite3.Error as exc:
        logger.warning("computers_view_unreadable", error_type=type(exc).__name__)
        raise _error(503, "computers_unavailable", "the datastore could not answer") from None


@router.post("/invites", status_code=201)
async def post_invite(request: Request) -> Dict[str, Any]:
    """Mint an invite and open the join port. Output: ``{id, code|null, link, expires_at, addresses, fid_short}``.

    409 ``joined_computer`` on a member, 409 ``setup_incomplete``, 409 ``too_many_invites`` (four live), 429 ``invite_rate``.
    ``code`` is null while code mode is paused (the link still works). Example: ``(await post_invite(request))["code"]`` -> "042917".
    """
    rt = await _inviter()
    if not _INVITE_WINDOW.hit("invites", time.monotonic()):
        raise _error(429, "invite_rate", "too many invites, wait a minute")
    try:
        inv = rt.invites.mint("code")
    except MemberRefused:
        raise _error(409, "joined_computer", "this computer joined a pack; it adds no computers") from None
    except TooManyInvites:
        raise _error(409, "too_many_invites", "four invites are open; cancel one first") from None
    try:
        await rt.join_server.sync()
    except OSError as exc:
        logger.warning("computers_join_port_failed", error_type=type(exc).__name__)
    logger.info("computer_invite_minted", invite=inv.id)
    fid = rt.fed_key.device_id if rt.fed_key is not None else ""
    return {**_invite_json(rt, inv), "addresses": list(rt.addresses), "fid_short": fid[:view.FID_SHORT_LEN]}


@router.get("/invites/{invite_id}")
async def get_invite(invite_id: str, request: Request) -> Dict[str, Any]:
    """Show a live invite again. Output: ``{id, code|null, link, expires_at, attempts_left}``; 404 ``invite_not_found`` when it is gone."""
    rt = _rt()
    inv = next((i for i in (rt.invites.live() if rt.invites is not None else []) if i.id == invite_id), None)
    if inv is None:
        raise _error(404, "invite_not_found", "no live invite with that id")
    return _invite_json(rt, inv)


@router.delete("/invites/{invite_id}")
async def delete_invite(invite_id: str, request: Request) -> Dict[str, bool]:
    """Cancel an invite; the join port closes with the last one. Output: ``{"deleted": true}``; 404 ``invite_not_found``."""
    rt = _rt()
    if rt.invites is None or not rt.invites.cancel(invite_id):
        raise _error(404, "invite_not_found", "no live invite with that id")
    return {"deleted": True}


def _find_computer(rt: runtime.ComputersRuntime, iid: str) -> Optional[Dict[str, Any]]:
    with closing(rt.open_db()) as conn:
        return next((c for c in view.read_computers(conn, rt, _links()) if c["install_id"] == iid), None)


@router.delete("/peers/{install_id}")
async def delete_computer(install_id: str, request: Request) -> Dict[str, Any]:
    """Remove a computer (design 1.6): the courtesy call first, then the one cleanup. Output: ``{removed, peer_told}``; 404 ``computer_not_found``."""
    rt = _rt()
    if await asyncio.to_thread(_find_computer, rt, install_id) is None:
        raise _error(404, "computer_not_found", "no computer with that id")
    told = await membership.forget(install_id, notify_peer=True)
    return {"removed": True, "peer_told": told}


def _set_direction(rt: runtime.ComputersRuntime, iid: str, inbound: bool) -> Optional[Dict[str, Any]]:
    with closing(rt.open_db()) as conn:
        known = store.get(conn, iid) is not None or peer_hosts.get(conn, iid) is not None
        if not known:
            return None
        store.set_direction(conn, iid, inbound)
        grant = grants.live_for_peer(conn, iid)
        entry = next(c for c in view.read_computers(conn, rt, _links()) if c["install_id"] == iid)
    return {"entry": entry, "grant_id": grant.grant_id if grant is not None else None}


@router.put("/peers/{install_id}/direction")
async def put_direction(install_id: str, body: DirectionBody, request: Request) -> Dict[str, Any]:
    """Set whether a computer may control this one (design 3.3). ``one_way`` closes its held sockets. Output: the computer entry.

    404 ``computer_not_found``. An ssh-paired computer gets a ``computer_links`` row the first time. Example: body ``{"direction": "one_way"}``.
    """
    rt = _rt()
    one_way = body.direction == "one_way"
    done = await asyncio.to_thread(_set_direction, rt, install_id, not one_way)
    if done is None:
        raise _error(404, "computer_not_found", "no computer with that id")
    if one_way and done["grant_id"] is not None:
        await peer_sockets.close_grant(done["grant_id"])
    if rt.dialer is not None:
        rt.dialer.kick(install_id)
    rt.notify("computers")
    rt.notify("pack_relay_offer")
    logger.info("computer_direction_set", iid=install_id[:8], direction=body.direction)
    return done["entry"]


@router.post("/join", status_code=202)
async def post_join(body: JoinBody, request: Request) -> Dict[str, Any]:
    """A set-up computer joins a pack from the Pack page (the owner's login is the proof). Output: ``JoinStatus``.

    422 ``bad_request`` or ``bad_link``, 409 ``already_joined``, 503 ``unavailable``. Join has no MCP tool (its input is a secret).
    """
    _rt()
    before = join_job.current_job()
    try:
        job = membership.start_join(body.code, body.link, body.candidate_fid, origin="settings", totp_ok=True)
    except join_job.JoinNotAllowed as exc:
        raise _error(_JOIN_ERRORS.get(exc.code, 409), exc.code, "the join could not start") from None
    await terminal_helper.open_attach(job, created=job is not before)
    return job.status()


@router.post("/join/look", status_code=202)
async def post_join_look(request: Request) -> Dict[str, Any]:
    """Look for a pack from the Pack page (#1622, the owner's login is the proof): same flow as ``POST /auth/join/look``. Output: ``JoinStatus``.

    Status comes from ``GET /computers/join``. 409 ``already_joined``, 503 ``unavailable``. A look has no MCP tool (a join has none).
    """
    _rt()
    before = join_job.current_job()
    try:
        job = join_job.start_look(origin="settings")
    except join_job.JoinNotAllowed as exc:
        raise _error(_JOIN_ERRORS.get(exc.code, 409), exc.code, "the look could not start") from None
    await terminal_helper.open_attach(job, created=job is not before)
    return job.status()


@router.get("/join")
async def get_join(request: Request) -> Dict[str, Any]:
    """The latest join job's ``JoinStatus``. Polled while the join dialog shows."""
    return join_job.window_status()


@router.post("/leave")
async def post_leave(request: Request) -> Dict[str, bool]:
    """A member leaves its pack (design 1.6): courtesy to main, then the one cleanup. Output: ``{left, main_told}``; 409 ``not_member``."""
    rt = _rt()

    def main_iid() -> Optional[str]:
        with closing(rt.open_db()) as conn:
            row = store.main_row(conn)
        return row.peer_install_id if row is not None else None

    iid = await asyncio.to_thread(main_iid)
    if iid is None:
        raise _error(409, "not_member", "this computer has not joined a pack")
    told = await membership.forget(iid, notify_peer=True)
    return {"left": True, "main_told": told}


def _destination(body: AddPreviewBody) -> ssh_exec.SshDestination:
    try:
        return ssh_exec.SshDestination(body.ssh_target, body.ssh_port)
    except ssh_exec.SshArgumentError:
        raise _error(422, "bad_target", "use an ssh alias or user@host, and a port from 1 to 65535") from None


def _paired_with(rt: runtime.ComputersRuntime, dest: ssh_exec.SshDestination) -> bool:
    host = dest.target.rpartition("@")[2]
    with closing(rt.open_db()) as conn:
        return any(p.ssh_target.rpartition("@")[2] == host and (p.ssh_port is None or dest.port is None or p.ssh_port == dest.port)
                   for p in peer_hosts.list_peers(conn))


async def _preview(rt: runtime.ComputersRuntime, dest: ssh_exec.SshDestination) -> Dict[str, Any]:
    over = add_over_ssh.installer_override(rt.config_path)
    doc = await add_preview.preview(dest, paired=await asyncio.to_thread(_paired_with, rt, dest),
                                    installer_script=over["script"] if over else None)
    add_preview.remember(dest, doc)
    return doc


@router.post("/add/preview")
async def post_add_preview(body: AddPreviewBody, request: Request) -> Dict[str, Any]:
    """What adding a computer over ssh would do, changing nothing (design 8). Output: ``AddPreview`` with its blockers.

    422 ``bad_target``, 429 ``add_preview_rate``, 409 on a member or before setup. Example: body ``{"ssh_target": "alex@studio"}``.
    """
    rt = await _inviter()
    dest = _destination(body)
    if not _PREVIEW_WINDOW.hit("preview", time.monotonic()):
        raise _error(429, "add_preview_rate", "too many previews, wait a minute")
    return await _preview(rt, dest)


@router.post("/add", status_code=202)
async def post_add(body: AddBody, request: Request) -> Dict[str, str]:
    """Install Carnivore on the target over ssh and join it to this pack (design 8). Output: ``{"job_id"}``; follow it with ``GET /computers/add/{job_id}``.

    409 ``add_running`` for the same target, 409 ``target_blocked`` (with ``blockers``) when the fresh preview has one, 409 ``host_key_changed``
    when the key is not the one the owner approved. Example: body ``{"ssh_target": "alex@studio", "host_key_sha256": "SHA256:..."}``.
    """
    rt = await _inviter()
    dest = _destination(body)
    if add_over_ssh.JOBS.active_for(dest.target, dest.port) is not None:
        raise _error(409, "add_running", "this computer is already being added")
    doc = await _preview(rt, dest)
    if doc["blockers"]:
        raise HTTPException(status_code=409, detail={"code": "target_blocked", "detail": "the computer cannot be added yet",
                                                     "blockers": doc["blockers"]})
    if doc["host_key_sha256"] != body.host_key_sha256:
        raise _error(409, "host_key_changed", "the host key is not the one that was approved")
    if add_over_ssh.JOBS.active_for(dest.target, dest.port) is not None:
        raise _error(409, "add_running", "this computer is already being added")
    job = add_over_ssh.JOBS.start(rt, dest, body.host_key_sha256)
    logger.info("computer_add_started", job=job.id)
    return {"job_id": job.id}


@router.get("/add/{job_id}")
async def get_add_job(job_id: str, request: Request) -> Dict[str, Any]:
    """One add job: state, step, error code and the new computer's install id once joined. 404 ``job_not_found``."""
    _rt()
    job = add_over_ssh.JOBS.get(job_id)
    if job is None:
        raise _error(404, "job_not_found", "no add job with that id")
    return next(j for j in add_over_ssh.JOBS.snapshot() if j["id"] == job.id)
