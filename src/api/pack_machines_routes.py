
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from src.api.auth import require_auth
from src.core.federation import peer_links
from src.core.pack.machines import exchange, runtime
from src.core.pack.machines.settings_doc import PlacementModel
from src.core.relay_identity.device_key import DeviceKeyUnavailable

router = APIRouter(prefix="/pack", tags=["pack-machines"], dependencies=[Depends(require_auth)])


class MasterBody(BaseModel):
    """Which machine becomes master: an install id, or a label."""

    model_config = ConfigDict(extra="forbid")

    machine: str = Field(min_length=1, max_length=64)


class SettingsBody(BaseModel):
    """Pack-wide settings; only the named fields change (``placement_model: null`` clears the model)."""

    model_config = ConfigDict(extra="forbid")

    placement_mode: Optional[str] = Field(default=None, pattern="^(stats|enhanced)$")
    auto_distribute: Optional[bool] = None
    placement_model: Optional[PlacementModel] = None


class TracksMasterBody(BaseModel):

    model_config = ConfigDict(extra="forbid")

    tracks_master: StrictBool


class ReserveBody(BaseModel):
    """A partial reserve: each named section merges field by field."""

    model_config = ConfigDict(extra="forbid")

    in_use: Optional[Dict[str, Any]] = None
    away: Optional[Dict[str, Any]] = None
    schedule: Optional[Dict[str, Any]] = None
    keyboard_rule: Optional[Dict[str, Any]] = None


class RestrictionsBody(BaseModel):
    """A partial restrictions document; only the fields sent change (``max_agents: null`` means no cap)."""

    model_config = ConfigDict(extra="forbid")

    may_install_tools: Optional[StrictBool] = None
    may_receive_credentials: Optional[StrictBool] = None
    may_update_carnivore: Optional[StrictBool] = None
    may_host_agents: Optional[StrictBool] = None
    may_receive_projects: Optional[StrictBool] = None
    max_agents: Optional[int] = Field(default=None, ge=0, le=10000)
    allowed_projects: Optional[list] = Field(default=None, max_length=500)
    allowed_companies: Optional[list] = Field(default=None, max_length=500)


def _wired() -> runtime.Wiring:
    wired = runtime.wiring()
    if wired is None:
        raise HTTPException(503, {"code": "pack_unavailable", "detail": "the Pack machine layer is not running"})
    return wired


def _resolve(wired: runtime.Wiring, machine: str, peers: list) -> str:
    found = wired.runtime.resolve(machine, peers)
    if found is None:
        raise HTTPException(404, {"code": "machine_unknown", "detail": f"no machine in the Pack matches {machine[:64]}"})
    return found


async def _forward(install_id: str, path: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    links = peer_links.LINKS
    client = links.client(install_id) if links is not None else None
    if client is None:
        raise HTTPException(502, {"code": "machine_unreachable", "detail": "that machine's link is not up"})
    try:
        status, data = await exchange.post_via(client, 10.0)("PUT", path, {"patch": patch})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, {"code": "machine_unreachable", "detail": type(exc).__name__}) from None
    if status != 200:
        detail = (data or {}).get("detail") if isinstance(data, dict) else None
        raise HTTPException(status, detail or {"code": "peer_refused", "detail": f"the machine answered {status}"})
    return data if isinstance(data, dict) else {}


def _entry_snapshot(wired: runtime.Wiring, install_id: str) -> Dict[str, Any]:
    entry = wired.runtime.roster.entries.get(install_id)
    if entry is None or entry.snapshot is None:
        raise HTTPException(409, {"code": "machine_not_heard", "detail": "that machine has not answered an exchange yet"})
    return entry.snapshot


@router.get("/machines")
async def get_machines(request: Request, agents: bool = Query(False)) -> Dict[str, Any]:
    """Every machine in the Pack with specs, live stats, reserve, restrictions and capabilities; the master marked.

    ``agents`` is accepted for P10 (per-agent load) and ignored until it ships. A machine whose link is down, or whose
    snapshot is older than 30 s, shows ``snapshot: null``, never zeros.
    """
    wired = _wired()
    wired.runtime.touch()
    peers = await asyncio.to_thread(wired.peers)
    return await asyncio.to_thread(wired.runtime.view, peers)


async def _edit(wired: Any, changes: Dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(wired.runtime.edit_settings, changes)
    except DeviceKeyUnavailable:
        raise HTTPException(503, {"code": "signing_unavailable",
                                  "detail": "this computer's federation key could not be read, so the change was not signed"}) from None


@router.put("/master")
async def put_master(body: MasterBody, request: Request) -> Dict[str, Any]:
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, body.machine, peers)
    await _edit(wired, {"master_install_id": target})
    wired.runtime.kick()
    return await asyncio.to_thread(wired.runtime.view, peers)


@router.put("/settings")
async def put_settings(body: SettingsBody, request: Request) -> Dict[str, Any]:
    """Change Pack-wide settings (placement mode, auto-distribute, the enhanced placement model)."""
    wired = _wired()
    changes = body.model_dump(exclude_unset=True, mode="json")
    if not changes:
        raise HTTPException(422, {"code": "nothing_to_change", "detail": "name at least one setting"})
    held = await asyncio.to_thread(wired.runtime.settings)
    if held.master_install_id != wired.runtime.install_id:
        raise HTTPException(409, {"code": "not_alpha", "alpha": held.master_install_id,
                                  "detail": "pack settings are changed on alpha; change them there"})
    try:
        await _edit(wired, changes)
    except ValueError as exc:
        raise HTTPException(422, {"code": "settings_invalid", "detail": " ".join(str(exc).split())[:300]}) from None
    wired.runtime.kick()
    peers = await asyncio.to_thread(wired.peers)
    return await asyncio.to_thread(wired.runtime.view, peers)


@router.get("/tracks-master")
async def get_tracks_master(request: Request) -> Dict[str, Any]:
    wired = _wired()
    return {"tracks_master": await asyncio.to_thread(wired.state.tracks_master)}


@router.put("/tracks-master")
async def put_tracks_master(body: TracksMasterBody, request: Request) -> Dict[str, Any]:
    """
    Applies at once: the refresh scope granted to every paired machine is re-derived. Example: PUT /api/v1/pack/tracks-master {"tracks_master": false}
    """
    wired = _wired()
    try:
        await asyncio.to_thread(wired.state.save_tracks_master, body.tracks_master)
    except (OSError, ValueError) as exc:
        raise HTTPException(500, {"code": "config_unwritable", "detail": type(exc).__name__}) from None
    await asyncio.to_thread(wired.sync_scopes)
    return {"tracks_master": body.tracks_master}


@router.get("/machines/{machine}/reserve")
async def get_reserve(machine: str, request: Request) -> Dict[str, Any]:
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, machine, peers)
    snap = await asyncio.to_thread(wired.runtime.own_snapshot) if target == wired.runtime.install_id else _entry_snapshot(wired, target)
    reserve = snap.get("reserve") or {}
    return {"machine": target, "active": {k: reserve.get(k) for k in ("level", "cpu_pct", "mem_pct", "source")},
            "reserve": reserve.get("config")}


@router.put("/machines/{machine}/reserve")
async def put_reserve(machine: str, body: ReserveBody, request: Request) -> Dict[str, Any]:
    """Edit a machine's reserve from any machine (a comfort setting); the machine itself enforces it."""
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, machine, peers)
    patch = body.model_dump(exclude_none=True)
    if target == wired.runtime.install_id:
        try:
            cfg = await asyncio.to_thread(wired.runtime.set_reserve, patch)
        except ValueError as exc:
            raise HTTPException(422, {"code": "reserve_invalid", "detail": " ".join(str(exc).split())[:300]}) from None
        return {"machine": target, "reserve": cfg.model_dump()}
    return {"machine": target, **await _forward(target, exchange.RESERVE_PATH, patch)}


@router.get("/machines/{machine}/restrictions")
async def get_restrictions(machine: str, request: Request) -> Dict[str, Any]:
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, machine, peers)
    if target == wired.runtime.install_id:
        found = (await asyncio.to_thread(wired.state.restrictions)).model_dump()
    else:
        found = _entry_snapshot(wired, target).get("restrictions")
    return {"machine": target, "restrictions": found}


@router.put("/machines/{machine}/restrictions")
async def put_restrictions(machine: str, body: RestrictionsBody, request: Request) -> Dict[str, Any]:
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, machine, peers)
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(422, {"code": "nothing_to_change", "detail": "name at least one restriction"})
    if target == wired.runtime.install_id:
        try:
            new = await asyncio.to_thread(wired.runtime.set_restrictions, patch, from_peer=False)
        except ValueError as exc:
            raise HTTPException(422, {"code": "restrictions_invalid", "detail": " ".join(str(exc).split())[:300]}) from None
        await asyncio.to_thread(wired.sync_scopes)
        return {"machine": target, "restrictions": new.model_dump()}
    return {"machine": target, **await _forward(target, exchange.TIGHTEN_PATH, patch)}


@router.post("/machines/self/rescan")
async def rescan_self(request: Request) -> Dict[str, Any]:
    wired = _wired()
    toolchain = await asyncio.to_thread(wired.runtime.collector.rescan)
    return {"toolchain": toolchain}
