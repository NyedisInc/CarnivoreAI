
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.core.computers import direction
from src.core.pack.skills import alerts, apply as skills_apply, owner, rules, take, warez_alpha, wiring
from src.core.pack.skills.doc import Choices
from src.core.pack.skills.runtime import SkillsSync
from src.core.pack.skills.scan import RootScan, scan_root
from src.core.resource_push import notifier
from src.core.resource_push.topics import LOCAL_SKILLS

logger = structlog.get_logger()
router = APIRouter(prefix="/pack/skills", tags=["pack-skills"], dependencies=[Depends(require_auth)])
TOKENS = owner.PlanTokens()
Pairs = List[List[str]]


class ChoicesBody(BaseModel):
    """Alpha's choices: ``mode`` off, some (``include`` only) or all (everything except ``exclude``). ``dry_run`` defaults to true."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["off", "some", "all"]
    include: Pairs = Field(default_factory=list, max_length=rules.MAX_SKILLS * 2)
    exclude: Pairs = Field(default_factory=list, max_length=rules.MAX_SKILLS * 2)
    dry_run: bool = True
    plan_token: Optional[str] = Field(default=None, max_length=128)


class SkillBody(BaseModel):
    """Turn one skill on or off. ``remove_elsewhere`` (off only) trashes the other computers' copies, kept 14 days there."""

    model_config = ConfigDict(extra="forbid")

    synced: bool
    families: List[str] = Field(default_factory=list, max_length=len(rules.FAMILIES))
    remove_elsewhere: bool = False
    dry_run: bool = True
    plan_token: Optional[str] = Field(default=None, max_length=128)


class HeldBody(BaseModel):
    """What to do with a ``missing on alpha`` row, or (``publish_mine``) with a new alpha that holds because it is behind."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["stop_syncing", "remove_everywhere", "publish_mine"]


class TrashPlacedBody(BaseModel):

    model_config = ConfigDict(extra="forbid")

    from_install_id: str = Field(min_length=1, max_length=64)


class TakeBody(BaseModel):
    """Take another computer's copy of one skill into alpha: a dry run first (it answers what would land and a plan token), then the write."""

    model_config = ConfigDict(extra="forbid")

    from_install_id: str = Field(min_length=1, max_length=64)
    family: str = Field(max_length=16)
    name: str = Field(max_length=rules.MAX_NAME_BYTES)
    dry_run: bool = True
    plan_token: Optional[str] = Field(default=None, max_length=128)


def _sync() -> SkillsSync:
    if wiring.SYNC is None:
        raise HTTPException(503, {"code": "skills_unavailable", "detail": "skill sync is not running"})
    return wiring.SYNC


def _label(sync: SkillsSync, install_id: str) -> str:
    for view in sync.peer_views():
        if view.peer_id == install_id:
            return view.label
    return "this computer" if install_id == sync.install_id else ""


async def _alpha(sync: SkillsSync) -> None:
    held = await asyncio.to_thread(sync.refresh_alpha)
    if not sync.is_alpha():
        raise HTTPException(409, {"code": "not_alpha", "alpha_install_id": held, "alpha_label": _label(sync, held),
                                  "detail": f"alpha decides what syncs. change it on {_label(sync, held) or 'alpha'}."})


def _pair(family: str, name: str) -> tuple[str, str]:
    if family not in rules.FAMILIES or rules.skill_name_problem(name) is not None or rules.nfc(name) != name:
        raise HTTPException(422, {"code": "bad_skill", "detail": "not a skill name this sync can carry"})
    return family, name


def _choices(body: ChoicesBody) -> Choices:
    for pair in [*body.include, *body.exclude]:
        if len(pair) != 2:
            raise HTTPException(422, {"code": "bad_skill", "detail": "a skill is [family, name]"})
        _pair(pair[0], pair[1])
    return owner.with_mode(body.mode, body.include, body.exclude)


def _scans(sync: SkillsSync) -> Dict[str, RootScan]:
    return {family: scan_root(root, family) for family, root in sync.roots().items()}


async def _plan_or_write(sync: SkillsSync, new: Choices, action: Dict[str, Any], dry_run: bool, token: Optional[str],
                         queue: Dict[str, Any], focus: Optional[List[tuple[str, str]]] = None) -> Dict[str, Any]:
    inventories = await owner.fetch_inventories(sync.peer_views(), sync.request_to)
    fp = owner.fingerprint({**owner.choices_json(new), **action}, inventories)
    if dry_run:
        scans = await asyncio.to_thread(_scans, sync)
        partial = any(i.state == owner.PARTIAL for i in inventories)
        wplan = await asyncio.to_thread(warez_alpha.plan, sync.services(), sync.roots())
        return {**owner.preview(new, scans, inventories, wplan.entries, wplan.pairs, focus), "choices": owner.choices_json(new),
                "plan_token": None if partial else TOKENS.issue(fp)}
    if not token:
        raise HTTPException(409, {"code": "plan_required", "detail": "run the dry run first and send its plan_token"})
    if not TOKENS.redeem(token, fp):
        raise HTTPException(409, {"code": "plan_stale", "detail": "a computer or the choices changed since the dry run; run it again"})
    try:
        await asyncio.to_thread(sync.choices.write, new)
    except (OSError, ValueError) as exc:
        logger.warning("pack_skills_choices_write_failed", error=type(exc).__name__)
        raise HTTPException(503, {"code": "config_write_failed", "detail": "could not write config.json"}) from None
    if queue["removals"] or queue["unsynced"]:
        await asyncio.to_thread(sync.queue_entries, queue["removals"], queue["unsynced"])
    sync.reset_caps()
    sync.notify()
    sync.kick()
    return {"ok": True, "choices": owner.choices_json(new)}


@router.get("")
async def get_skills(inventory: bool = Query(False), kick: bool = Query(True)) -> Dict[str, Any]:
    """The matrix: every personal skill with its state and one cell per computer. Alpha also kicks a debounced publish pass.
    """
    sync = _sync()
    held = await asyncio.to_thread(sync.refresh_alpha)
    if kick:
        sync.kick()
    if not sync.is_alpha():
        return await asyncio.to_thread(owner.receiver_view, sync, held, _label(sync, held))
    inventories = await owner.fetch_inventories(sync.peer_views(), sync.request_to) if inventory else []
    scans = await asyncio.to_thread(_scans, sync)
    choices = await asyncio.to_thread(sync.choices.read)
    return await asyncio.to_thread(owner.matrix, sync, choices, scans, inventories, _label(sync, held))


@router.put("/choices")
async def put_choices(body: ChoicesBody) -> Dict[str, Any]:
    """Set the mode and the include / leave-out lists. Alpha only; ``dry_run`` first, then the write with its ``plan_token``."""
    sync = _sync()
    await _alpha(sync)
    new = _choices(body)
    return await _plan_or_write(sync, new, {}, body.dry_run, body.plan_token, {"removals": [], "unsynced": []})


@router.put("/{family}/{name}")
async def put_skill(family: str, name: str, body: SkillBody) -> Dict[str, Any]:
    """Turn one skill on or off. Off keeps the other computers' copies unless ``remove_elsewhere``. Alpha only, two steps as above."""
    sync = _sync()
    await _alpha(sync)
    pair = _pair(family, name)
    for extra in body.families:
        _pair(extra, name)
    pairs = sorted({pair, *((f, name) for f in body.families)})
    new = await asyncio.to_thread(sync.choices.read)
    for f, n in pairs:
        new = owner.with_skill(new, f, n, body.synced)
    removing = bool(not body.synced and body.remove_elsewhere)
    queue = {"removals": pairs if removing else [],
             "unsynced": pairs if (not body.synced and not removing) else []}
    action = {"skill": list(pair), "synced": body.synced, "remove": removing}
    if len(pairs) > 1:
        action["skills"] = [list(p) for p in pairs]
    return await _plan_or_write(sync, new, action, body.dry_run, body.plan_token, queue, pairs)


@router.post("/{family}/{name}/held")
async def post_held(family: str, name: str, body: HeldBody) -> Dict[str, Any]:
    """Resolve a held row. Alpha only. ``stop_syncing`` and ``remove_everywhere`` need the skill to be in the published ``held`` list."""
    sync = _sync()
    await _alpha(sync)
    pair = _pair(family, name)
    if body.action == "publish_mine":
        outcome = await asyncio.to_thread(sync.publish_pass, force=True)
        sync.kick()
        return {"ok": True, "outcome": outcome.outcome}
    doc = await asyncio.to_thread(sync.published) or {}
    if not any((f, n) == pair for f, n, _ in doc.get("held", [])):
        raise HTTPException(404, {"code": "not_held", "detail": "that skill is not held"})
    new = owner.with_skill(await asyncio.to_thread(sync.choices.read), family, name, False)
    try:
        await asyncio.to_thread(sync.choices.write, new)
    except (OSError, ValueError) as exc:
        logger.warning("pack_skills_choices_write_failed", error=type(exc).__name__)
        raise HTTPException(503, {"code": "config_write_failed", "detail": "could not write config.json"}) from None
    remove = body.action == "remove_everywhere"
    await asyncio.to_thread(sync.queue_entries, [pair] if remove else [], [] if remove else [pair])
    sync.reset_caps()
    sync.notify()
    sync.kick()
    return {"ok": True, "choices": owner.choices_json(new)}


@router.post("/sync-now")
async def post_sync_now() -> Dict[str, Any]:
    """Alpha: publish and deliver to every computer now and reset the re-delivery caps. Any other computer: check its own copies."""
    return {"ok": True, "did": await _sync().sync_now()}


@router.post("/trash-placed")
async def post_trash_placed(body: TrashPlacedBody) -> Dict[str, Any]:
    sync = _sync()
    pairs = await asyncio.to_thread(owner.trash_placed, sync.state, body.from_install_id, sync.receive_roots(), None, sync.services())
    if pairs:
        notifier.notify(LOCAL_SKILLS)
    sync.notify()
    await asyncio.to_thread(alerts.check_placers, sync.state)
    return {"ok": True, "trashed": len(pairs), "skills": [list(p) for p in pairs]}


TAKE_STATUS = {"not_found": 404, "unreachable": 502}


@router.post("/take")
async def post_take(body: TakeBody) -> Dict[str, Any]:
    sync = _sync()
    await _alpha(sync)
    family, name = _pair(body.family, body.name)
    view = next((v for v in sync.peer_views() if v.peer_id == body.from_install_id), None)
    if view is None or body.from_install_id == sync.install_id:
        raise HTTPException(404, {"code": "unknown_computer", "detail": "that is not another computer in this Pack"})
    if direction.contained(view.peer_id):
        raise HTTPException(409, {"code": "computer_one_way", "detail": f"{view.label} is one way here; nothing is taken from it"})
    if not view.has_take_cap():
        raise HTTPException(409, {"code": "needs_update", "detail": f"{view.label} runs an older carnivore. update it, then take its copy."})
    request = sync.request_to(view.peer_id) if view.up else None
    if request is None:
        raise HTTPException(409, {"code": "offline", "detail": f"{view.label} is not connected right now"})
    stage_root = sync.state.path.parent / "skills-take"
    try:
        taken = await take.fetch_copy(request, family, name, stage_root)
    except take.TakeError as exc:
        raise HTTPException(TAKE_STATUS.get(exc.code, exc.status), {"code": exc.code, "detail": exc.detail or exc.code.replace("_", " ")}) from None
    try:
        mine = await asyncio.to_thread(take.local_state, sync.receive_roots(), family, name)
        fp = owner.fingerprint({"take": [view.peer_id, family, name], "digest": taken.scan.digest, "here": mine}, [])
        if body.dry_run:
            shown = await asyncio.to_thread(take.preview, taken, family, name, sync.receive_roots())
            return {**shown, "from": view.label, "plan_token": TOKENS.issue(fp)}
        if not body.plan_token:
            raise HTTPException(409, {"code": "plan_required", "detail": "run the dry run first and send its plan_token"})
        if not TOKENS.redeem(body.plan_token, fp):
            raise HTTPException(409, {"code": "plan_stale", "detail": f"{view.label}'s copy or the choices changed since the dry run; run it again"})
        placed = await asyncio.to_thread(skills_apply.place_skill, sync.receive_roots(), family, name, taken.bundle, taken.scan.digest)
    finally:
        await asyncio.to_thread(taken.cleanup)
    sync.notify()
    sync.kick()
    conflicts = [reason for _group, reason in placed if reason]
    return {"ok": not conflicts and bool(placed), "placed": len(placed) - len(conflicts), "conflicts": conflicts}


@router.get("/{family}/{name}")
async def get_skill(family: str, name: str) -> Dict[str, Any]:
    sync = _sync()
    pair = _pair(family, name)
    held = await asyncio.to_thread(sync.refresh_alpha)
    scan = await asyncio.to_thread(lambda: scan_root(sync.roots()[family], family).skills.get(name))
    out: Dict[str, Any] = {"family": family, "name": name, "role": "alpha" if sync.is_alpha() else "receiver",
                           "alpha": {"id": held, "label": _label(sync, held)}, "machine_local": sorted(rules.MACHINE_LOCAL_NAMES),
                           "here": None}
    if scan is not None:
        out["here"] = {"digest": scan.digest, "problem": scan.problem, "scripts": owner.scripts_of(scan),
                       "files": [{"path": f.path, "size": f.size, "mode": f.mode, "sha256": f.sha256} for f in scan.files]}
    if sync.is_alpha():
        inventories = await owner.fetch_inventories(sync.peer_views(), sync.request_to)
        out["computers"] = [{"id": i.peer_id, "label": i.label, "state": i.state,
                             "digests": sorted({r[3] for r in i.rows if (r[0], r[1]) == pair}),
                             "from_warez": any(r[4] for r in i.rows if (r[0], r[1]) == pair)} for i in inventories]
    return out
