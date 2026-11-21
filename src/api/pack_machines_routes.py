
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from src.api.error_response import api_error
from src.api.auth import require_auth
from src.core import resource_push
from src.core.computers import runtime as computers_runtime
from src.core.federation import peer_links
from src.core.pack.reconnect import config as reconnect_config
from src.core.pack.machines import capabilities as caps_mod, exchange, reconnect_view, runtime
from src.core.pack.machines.settings_doc import PlacementModel
from src.core.relay_identity.device_key import DeviceKeyUnavailable
from src.core.resource_push import topics

router = APIRouter(prefix="/pack", tags=["pack-machines"], dependencies=[Depends(require_auth)])


class MasterBody(BaseModel):
    """Which machine becomes master: an install id, or a label."""

    model_config = ConfigDict(extra="forbid")

    machine: str = Field(min_length=1, max_length=64)


class ReconnectBody(BaseModel):
    """The owner's relay switch for this computer: true, false, or null for the build default. The field is required so null is a choice."""

    model_config = ConfigDict(extra="forbid")

    relay: Optional[StrictBool]
    takeover: Optional[StrictBool] = None


class SettingsBody(BaseModel):
    """Pack-wide settings; only the named fields change (``placement_model: null`` clears the model)."""

    model_config = ConfigDict(extra="forbid")

    placement_mode: Optional[str] = Field(default=None, pattern="^(stats|enhanced)$")
    auto_distribute: Optional[bool] = None
    placement_model: Optional[PlacementModel] = None


class SuccessorsBody(BaseModel):
    """The whole takeover order: every computer in the Pack once, by id or label, first in line first (#2980)."""
    model_config = ConfigDict(extra="forbid")
    order: List[str] = Field(min_length=2, max_length=16)


class EligibleBody(BaseModel):
    """Turn one computer's takeover eligibility on or off (#2980)."""
    model_config = ConfigDict(extra="forbid")
    machine: str = Field(min_length=1, max_length=128)
    eligible: StrictBool


class LabelsBody(BaseModel):
    """The whole label list for one computer (at most 16; each lowercase ``[a-z0-9][a-z0-9 ._-]{0,31}``, checked by the receiver)."""

    model_config = ConfigDict(extra="forbid")

    labels: List[str] = Field(max_length=16)


class TracksMasterBody(BaseModel):
    """Whether THIS machine refreshes its own install when the master's code lands."""

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
    may_receive_global_setup: Optional[StrictBool] = None
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
    return await _forward_call(install_id, "PUT", path, {"patch": patch})


async def _forward_call(install_id: str, method: str, path: str, body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    links = peer_links.LINKS
    client = links.client(install_id) if links is not None else None
    if client is None:
        raise HTTPException(502, {"code": "machine_unreachable", "detail": "that machine's link is not up"})
    try:
        status, data = await exchange.post_via(client, 45.0 if method == "POST" else 10.0)(method, path, body)
    except Exception as exc:  # noqa: BLE001
        raise api_error(502, "machine_unreachable", exc) from exc
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
    _wired().runtime.touch()
    return await machines_view()


async def machines_view() -> Dict[str, Any]:
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    return await asyncio.to_thread(_reconnect_fields, wired, await asyncio.to_thread(wired.runtime.view, peers))


def _reconnect_fields(wired: runtime.Wiring, view: Dict[str, Any]) -> Dict[str, Any]:
    rt = computers_runtime.active()
    path = rt.config_path if rt is not None else None
    hub = rt.listener if rt is not None else None
    custody = wired.runtime.custody
    try:
        relayed = frozenset(hub.relayed()) if hub is not None else frozenset()
    except RuntimeError:
        relayed = frozenset()
    return reconnect_view.augment(
        view, roster=custody.roster(), home_state=custody.home_state(), relayed=relayed,
        relay_known=lambda iid: path is not None and reconnect_config.learned_relay_id(path, iid) is not None,
        relay_on=reconnect_config.relay_on(path) if path is not None else False,
        takeover_on=reconnect_config.takeover_on(path) if path is not None else False)


async def _edit(wired: Any, changes: Dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(wired.runtime.edit_settings, changes)
    except DeviceKeyUnavailable:
        raise HTTPException(503, {"code": "signing_unavailable",
                                  "detail": "this computer's federation key could not be read, so the change was not signed"}) from None


@router.put("/master")
async def put_master(body: MasterBody, request: Request) -> Dict[str, Any]:
    """Make one machine the Pack master (an owner action here; it reaches the other machines by the exchange)."""
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, body.machine, peers)
    await _edit(wired, {"master_install_id": target})
    wired.runtime.kick()
    return await machines_view()


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
    return await machines_view()


def _reconnect_view(path: Any) -> Dict[str, Any]:
    return {"relay": reconnect_config.relay_choice(path), "relay_on": reconnect_config.relay_on(path),
            "takeover_on": reconnect_config.takeover_on(path)}


@router.get("/reconnect")
async def get_reconnect(request: Request) -> Dict[str, Any]:
    """This computer's Pack relay switch: the owner's choice and what is in force (the build default while never chosen)."""
    rt = computers_runtime.active()
    if rt is None:
        raise HTTPException(503, {"code": "computers_not_running", "detail": "the computers runtime is not running"})
    return await asyncio.to_thread(_reconnect_view, rt.config_path)


@router.put("/reconnect")
async def put_reconnect(body: ReconnectBody, request: Request) -> Dict[str, Any]:
    """Turn the Pack's relay path on or off on THIS computer (an Alpha with members opens its tunnel, a member that lost its Alpha dials it).

    Applies at once. Example: PUT /api/v1/pack/reconnect {"relay": false}
    """
    rt = computers_runtime.active()
    if rt is None:
        raise HTTPException(503, {"code": "computers_not_running", "detail": "the computers runtime is not running"})
    try:
        await asyncio.to_thread(reconnect_config.set_relay, rt.config_path, body.relay)
        if "takeover" in body.model_fields_set:
            await asyncio.to_thread(reconnect_config.set_takeover, rt.config_path, body.takeover)
    except (OSError, ValueError) as exc:
        raise api_error(500, "config_unwritable", exc) from exc
    await rt.relay_switch_changed()
    return await asyncio.to_thread(_reconnect_view, rt.config_path)


@router.get("/tracks-master")
async def get_tracks_master(request: Request) -> Dict[str, Any]:
    """Whether this machine follows the master's code (on by default): a landing worker's refresh reaches it only when on."""
    wired = _wired()
    return {"tracks_master": await asyncio.to_thread(wired.state.tracks_master)}


@router.put("/tracks-master")
async def put_tracks_master(body: TracksMasterBody, request: Request) -> Dict[str, Any]:
    """Turn this machine's follow-the-master refresh on or off. It also needs the machine's own ``may_update_carnivore`` rule.

    Applies at once: the refresh scope granted to every paired machine is re-derived. Example: PUT /api/v1/pack/tracks-master {"tracks_master": false}
    """
    wired = _wired()
    try:
        await asyncio.to_thread(wired.state.save_tracks_master, body.tracks_master)
    except (OSError, ValueError) as exc:
        raise api_error(500, "config_unwritable", exc) from exc
    await asyncio.to_thread(wired.sync_scopes)
    resource_push.notify(topics.PACK_TRACKS_MASTER)
    return {"tracks_master": body.tracks_master}


@router.get("/machines/{machine}/reserve")
async def get_reserve(machine: str, request: Request) -> Dict[str, Any]:
    """One machine's reserve settings and the level in force there now."""
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
            raise api_error(422, "reserve_invalid", exc) from None
        return {"machine": target, "reserve": cfg.model_dump()}
    return {"machine": target, **await _forward(target, exchange.RESERVE_PATH, patch)}


@router.get("/machines/{machine}/restrictions")
async def get_restrictions(machine: str, request: Request) -> Dict[str, Any]:
    """One machine's restrictions as that machine last reported them."""
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
    """Change a machine's restrictions. On THIS machine any change; on a peer only a tightening (that machine refuses a
    loosening with ``403 pack_restricted``: restrictions protect a machine from its peers, so only its own owner loosens)."""
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
            raise api_error(422, "restrictions_invalid", exc) from None
        await asyncio.to_thread(wired.sync_scopes)
        return {"machine": target, "restrictions": new.model_dump()}
    return {"machine": target, **await _forward(target, exchange.TIGHTEN_PATH, patch)}


@router.post("/machines/self/rescan")
async def rescan_self(request: Request) -> Dict[str, Any]:
    """The old path of this computer's rescan, kept as an alias of ``POST /pack/machines/self/rescan`` under the new route."""
    return await rescan_machine("self", request)


@router.post("/machines/{machine}/rescan")
async def rescan_machine(machine: str, request: Request) -> Dict[str, Any]:
    """Re-probe one computer's toolchain and abilities now (otherwise once a day). At most one abilities probe per 60 s per computer:
    a call inside that window answers the current block with ``fresh: false``. Another computer's rescan is forwarded to it.

    Example: POST /api/v1/pack/machines/tower/rescan -> {"machine": "...", "toolchain": {...}, "can": {...}, "fresh": true}
    """
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, machine, peers)
    if target == wired.runtime.install_id:
        return {"machine": target, **await asyncio.to_thread(wired.rescan_self)}
    return {"machine": target, **await _forward_call(target, "POST", exchange.RESCAN_PATH, None)}


@router.get("/machines/{machine}/labels")
async def get_labels(machine: str, request: Request) -> Dict[str, Any]:
    """One computer's labels (what the owner calls it: ``rtx 4090``, ``fast disk``); another computer's as it last published them."""
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, machine, peers)
    if target == wired.runtime.install_id:
        return {"machine": target, "labels": await asyncio.to_thread(wired.state.labels)}
    can = _entry_snapshot(wired, target).get("can")
    labels = can.get("labels") if isinstance(can, dict) else None
    return {"machine": target, "labels": labels if isinstance(labels, list) else []}


@router.put("/machines/{machine}/labels")
async def put_labels(machine: str, body: LabelsBody, request: Request) -> Dict[str, Any]:
    """Replace one computer's labels from any computer (a placement hint, not a security line: a job asks for one as ``label:<text>``).

    A bad label is 422 ``labels_invalid``. Example: PUT /api/v1/pack/machines/doom/labels {"labels": ["rtx 4090"]}
    """
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, machine, peers)
    if target == wired.runtime.install_id:
        try:
            labels = await asyncio.to_thread(wired.set_labels, body.labels)
        except ValueError as exc:
            raise api_error(422, "labels_invalid", exc) from exc
        except OSError as exc:
            raise api_error(500, "config_unwritable", exc) from exc
        return {"machine": target, "labels": labels}
    return {"machine": target, **await _forward_call(target, "PUT", exchange.LABELS_PATH, {"labels": body.labels})}


async def _roster_edit(wired: Any, peers: list, *, order: Optional[List[str]] = None, eligible: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    held = await asyncio.to_thread(wired.runtime.settings)
    if held.master_install_id != wired.runtime.install_id:
        raise HTTPException(409, {"code": "not_alpha", "alpha": held.master_install_id,
                                  "detail": "the takeover order is changed on alpha; change it there"})
    rt = computers_runtime.active()
    if rt is None:
        raise HTTPException(503, {"code": "pack_unavailable", "detail": "the computers layer is not running"})
    try:
        inputs = await rt.roster_inputs()
        result = await asyncio.to_thread(wired.runtime.refresh_roster, inputs, order=order, eligible=eligible)
    except ValueError as exc:
        raise api_error(422, "roster_invalid", exc) from None
    except RuntimeError as exc:
        raise api_error(503, "roster_unavailable", exc) from None
    except DeviceKeyUnavailable:
        raise HTTPException(503, {"code": "signing_unavailable",
                                  "detail": "this computer's federation key could not be read, so the change was not signed"}) from None
    await rt.after_roster_change()
    wired.runtime.kick()
    held_roster = await asyncio.to_thread(wired.runtime.custody.roster)
    return {"changed": result, "generation": held_roster.generation if held_roster else None,
            "order": [c.install_id for c in held_roster.computers] if held_roster else [],
            "eligible": [c.install_id for c in held_roster.computers if c.takeover_eligible] if held_roster else []}


@router.put("/successors")
async def put_successors(body: SuccessorsBody, request: Request) -> Dict[str, Any]:
    """Set the takeover order (alpha only): who steps up first if alpha is lost. Example: PUT /api/v1/pack/successors {"order": ["doom", "nostromo"]}"""
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    order = [_resolve(wired, name, peers) for name in body.order]
    return await _roster_edit(wired, peers, order=order)


@router.put("/eligible")
async def put_eligible(body: EligibleBody, request: Request) -> Dict[str, Any]:
    """Allow or forbid one computer to take over (alpha only; seeded off). ON needs a computer that advertises ``pack.roster_v1``.

    Example: PUT /api/v1/pack/eligible {"machine": "doom", "eligible": true}
    """
    wired = _wired()
    peers = await asyncio.to_thread(wired.peers)
    target = _resolve(wired, body.machine, peers)
    if body.eligible and target != wired.runtime.install_id:
        info = next((p for p in peers if p.install_id == target), None)
        if info is None or not caps_mod.has(info.capabilities, caps_mod.CAP_ROSTER):
            raise HTTPException(409, {"code": "update_required",
                                      "detail": "that computer has not said it can follow a roster; update Carnivore there first"})
    return await _roster_edit(wired, peers, eligible={target: body.eligible})


def _same_origin(request: Request) -> None:
    origin, host = request.headers.get("origin"), request.headers.get("host", "")
    foreign = origin is not None and origin.split("://", 1)[-1] != host
    if foreign or request.headers.get("sec-fetch-site", "same-origin") == "cross-site":
        raise HTTPException(403, {"code": "foreign_origin", "detail": "this must come from the Carnivore page itself"})


@router.post("/interim/confirm")
async def post_interim_confirm(request: Request) -> Dict[str, Any]:
    """The owner's per-computer confirm of the Alpha this computer follows now ("confirm new main", #2980 PLAN C5 rule 5): sets THIS computer's local
    ``home_override`` and clears its ``interim``. Nothing is re-signed and no document changes ``home``.

    The owner's own UI session only: an API key is fenced (``core/api_keys/fence.py``), a peer or federation token is not a login, there is NO MCP tool
    for it (a ruling, ``docs/DECISIONS.md``), and a foreign origin is refused. Run it on every computer that should follow the new main.
    Raises 409 ``not_interim`` when this computer is not limited. Example: POST /api/v1/pack/interim/confirm
    """
    _same_origin(request)
    wired = _wired()
    try:
        changed = await asyncio.to_thread(wired.runtime.custody.confirm_local)
    except (OSError, ValueError) as exc:
        raise api_error(500, "config_unwritable", exc) from exc
    if not changed:
        raise HTTPException(409, {"code": "not_interim", "detail": "this computer is not limited: nothing to confirm"})
    wired.runtime.kick()
    return await machines_view()
