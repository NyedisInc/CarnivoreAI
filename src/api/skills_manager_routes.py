
from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.api.peer_auth import require_peer_sessions
from src.api.catalog_views import badge_for
from src.api.remote_route_guard import refuse_remote
from src.config import settings
from src.config.provider_accounts import MANAGED_ROOT, profile_dir_for
from src.core.account_switch.pane_account import read_pane_profile
from src.core.live_install_roots import CODEX_HOME_ENV_VAR
from src.core.provider_ledger import accounts_store
from src.core.resource_push import notifier
from src.core.resource_push.topics import LOCAL_SKILLS
from src.core import session_change_notice
from src.core.skill_manager import card_art, card_summary
from src.core.skill_manager.inventory import build_inventory
from src.core.skill_manager.local_skill_md import read_location_skill_md_hashed
from src.core.skill_manager.overrides_apply import apply_override
from src.core.skill_manager.remove import remove_location
from src.core.skill_manager.roots import known_profiles, profile_groups
from src.core.skill_manager.session_resolver import resolve_session_skills
from src.core.skill_manager.types import OverrideError, Profile
from src.core.skills.installer import trash_stamp
from src.core.skills.ledger_types import SCOPE_GLOBAL, SCOPE_PROJECT
from src.core.skills.project_scope import ProjectPathRefused, known_project_roots
from src.core.slash_command_discovery import discover_plugin_scope
from src.models.websocket import WSMessageType

logger = structlog.get_logger()

router = APIRouter(tags=["skills"])


def _profiles(home: Path) -> List[Profile]:
    try:
        accounts = accounts_store.list_accounts(Path(settings.auth_config_file).expanduser())
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("skills_inventory_accounts_unreadable", error=type(exc).__name__)
        accounts = []
    pairs = [(a.id, profile_dir_for(a)) for a in accounts if a.provider == "claude"]
    return known_profiles(pairs, home=home, managed_root=MANAGED_ROOT)


def _codex_home(home: Path) -> Path:
    raw = os.environ.get(CODEX_HOME_ENV_VAR)
    return Path(raw).expanduser() if raw and raw.strip() else home / ".codex"


def _resolve_project(state_dir: Path, project_path: str) -> str:
    real = os.path.realpath(os.path.expanduser(project_path))
    try:
        known = known_project_roots(state_dir)
    except ProjectPathRefused as exc:
        raise HTTPException(status_code=503, detail=exc.detail)
    if real not in known:
        raise HTTPException(status_code=404, detail="not one of this launcher's projects")
    return real


def _validate(
    request: Request, profile: Optional[str], project: Optional[str]
) -> Tuple[List[Profile], Optional[str]]:
    profiles = _profiles(Path.home())
    if profile is not None and profile not in {p.profile_id for p in profiles}:
        raise HTTPException(status_code=404, detail="unknown profile")
    if project is None:
        return profiles, None
    state_dir = request.app.state.services.settings_reader.state_dir()
    return profiles, _resolve_project(state_dir, project)


def _inventory_now(
    request: Request,
    profiles: List[Profile],
    profile: Optional[str],
    resolved: Optional[str],
    snapshot: Any,
) -> Dict[str, Any]:
    home = Path.home()
    with request.app.state.services.catalog.ledger() as ledger:
        rows = [
            row
            for row in ledger.list()
            if row.scope == SCOPE_GLOBAL or (row.scope == SCOPE_PROJECT and row.project_path == resolved)
        ]
        targets: Dict[str, Tuple[Any, ...]] = {row.install_id: ledger.targets(row.install_id) for row in rows}
    return build_inventory(
        profiles=profiles,
        profile_id=profile,
        project_path=resolved,
        home=home,
        codex_home=_codex_home(home),
        ledger_rows=rows,
        targets_for=lambda install_id: targets.get(install_id, ()),
        update_check=lambda row: badge_for(row, snapshot),
        plugin_scope=discover_plugin_scope,
    )


def _claude_group(profiles: List[Profile], profile: Optional[str]) -> Any:
    if not profiles:
        raise HTTPException(status_code=404, detail="no claude profile")
    chosen = next((p for p in profiles if p.profile_id == (profile or profiles[0].profile_id)), None)
    group = next((g for g in profile_groups(profiles) if chosen and chosen.profile_id in g.profiles), None)
    if chosen is None or group is None:
        raise HTTPException(status_code=404, detail="unknown profile")
    return replace(group, settings_path=os.path.realpath(os.path.join(chosen.directory, "settings.json")))


@router.get("/skills", dependencies=[Depends(require_auth)])
async def get_skills_inventory(
    request: Request,
    project_path: Optional[str] = None,
    profile: Optional[str] = None,
) -> Dict[str, Any]:
    """Every skill on disk for one Claude profile and, optionally, one project.

    Inputs: project_path - a known project's directory. profile - a known
    Claude profile id (default: ``~/.claude``'s).
    Output: the inventory (see ``docs/skills-manager.md``).
    Raises: HTTPException(404) unknown project or profile.
    """
    profiles, resolved = await asyncio.to_thread(_validate, request, profile, project_path)
    snapshot = await request.app.state.services.catalog.index_cache.get()
    inventory = await asyncio.to_thread(_inventory_now, request, profiles, profile, resolved, snapshot)
    await asyncio.to_thread(card_art.annotate, (loc for group in inventory["skills"] for loc in group["locations"]))
    await asyncio.to_thread(card_summary.annotate, (loc for group in inventory["skills"] for loc in group["locations"]))
    return inventory


class OverrideRequest(BaseModel):
    """Body of ``PUT /skills/overrides``. No field is a filesystem path."""

    harness: str
    file: str = Field(description="user | project | local")
    skill: str
    state: Optional[str] = Field(default=None, description="a state, or null to remove the override")
    project_path: Optional[str] = None
    profile: Optional[str] = None


@router.put("/skills/overrides", dependencies=[Depends(require_auth)])
async def put_skill_override(request: Request, body: OverrideRequest) -> Dict[str, Any]:
    """Switch one skill on, off or to a compact state for one harness and scope.

    Inputs: the body (harness claude|codex, file user|project|local, skill,
    state or null, project_path for a project scope, profile for Claude).
    Output: {harness, file, skill, state, wrote, restart_required, reload_hint}.
    Raises: HTTPException 404 unknown project or profile; 409 with
    ``{"code", "detail"}`` for plugin_managed, settings_unparseable,
    settings_changed, codex_config_edit_unsafe, target_unsafe; 400 bad input.
    """
    profiles, resolved = await asyncio.to_thread(_validate, request, body.profile, body.project_path)
    group = _claude_group(profiles, body.profile) if body.harness == "claude" else None
    home = Path.home()
    try:
        result = await asyncio.to_thread(
            apply_override,
            harness=body.harness,
            file=body.file,
            skill=body.skill,
            state=body.state,
            group=group,
            project_path=resolved,
            home=home,
            codex_home=_codex_home(home),
        )
    except OverrideError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail})
    if result["wrote"]:
        session_change_notice.publish(
            request.app.state,
            {"type": WSMessageType.SKILLS_CHANGED, "harness": body.harness, "file": body.file},
        )
        notifier.notify(LOCAL_SKILLS)
    return result


class RemoveRequest(BaseModel):
    """Body of ``DELETE /skills/locations/{location_id}``. No field is a filesystem path."""

    confirm: bool = False
    project_path: Optional[str] = Field(default=None, description="the context the id was listed in")
    profile: Optional[str] = None


@router.delete("/skills/locations/{location_id}", dependencies=[Depends(require_auth)])
async def delete_skill_location(request: Request, location_id: str, body: RemoveRequest) -> Dict[str, Any]:
    """Move one skill folder (or link) into its root's trash; never delete.

    The path is rebuilt server side from ``location_id`` against the CURRENT
    inventory for the named context, so an unknown or stale id is 404.
    Inputs: location_id (opaque, from ``GET /skills``); body ``{confirm: true,
    project_path?, profile?}``.
    Output: {location_id, name, trashed_to}.
    Raises: HTTPException 400 ``confirm_required``; 404 unknown project, profile,
    location or a folder already gone; 409 with ``{"code", "detail"}`` for
    read_only, use_catalog_uninstall, target_unsafe, trash_name_taken, not_a_skill_folder.
    """
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail={"code": "confirm_required", "detail": "send confirm: true"})
    profiles, resolved = await asyncio.to_thread(_validate, request, body.profile, body.project_path)
    snapshot = await request.app.state.services.catalog.index_cache.get()
    inventory = await asyncio.to_thread(_inventory_now, request, profiles, body.profile, resolved, snapshot)
    hit = next(
        (loc for group in inventory["skills"] for loc in group["locations"] if loc["location_id"] == location_id),
        None,
    )
    if hit is None:
        raise HTTPException(status_code=404, detail="unknown or stale location")
    root = next(r for r in inventory["roots"] if r["root_key"] == hit["root_key"])
    stamp = trash_stamp(request.app.state.services.clock)
    try:
        trashed_to = await asyncio.to_thread(remove_location, hit, root, stamp)
    except OverrideError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail})
    except OSError as exc:
        logger.warning("skill_location_remove_failed", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="the folder could not be moved to the trash")
    logger.info("skill_location_removed", location_id=location_id, harness=hit["harness"], scope=hit["scope"])
    session_change_notice.publish(
        request.app.state, {"type": WSMessageType.SKILLS_CHANGED, "harness": hit["harness"], "file": "location"}
    )
    notifier.notify(LOCAL_SKILLS)
    return {"location_id": location_id, "name": hit["name"], "trashed_to": trashed_to}


async def resolve_location(
    request: Request, location_id: str, project_path: Optional[str], profile: Optional[str]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    profiles, resolved = await asyncio.to_thread(_validate, request, profile, project_path)
    snapshot = await request.app.state.services.catalog.index_cache.get()
    inventory = await asyncio.to_thread(_inventory_now, request, profiles, profile, resolved, snapshot)
    hit = next(
        (loc for group in inventory["skills"] for loc in group["locations"] if loc["location_id"] == location_id),
        None,
    )
    if hit is None:
        raise HTTPException(status_code=404, detail="unknown or stale location")
    return hit, next(r for r in inventory["roots"] if r["root_key"] == hit["root_key"])


@router.get("/skills/locations/{location_id}/skill-md", dependencies=[Depends(require_auth)])
async def get_skill_location_md(
    request: Request, location_id: str, project_path: Optional[str] = None, profile: Optional[str] = None
) -> Dict[str, Any]:
    """The SKILL.md text of one listed skill location (capped, text only).

    The path is rebuilt server side from ``location_id`` against the CURRENT
    inventory for the named context; the client sends no path. Containment and
    a 64 KiB cap are enforced by ``read_location_skill_md_hashed``.
    Inputs: location_id (opaque, from ``GET /skills``); query ``project_path?``,
    ``profile?`` (the context the id was listed in).
    Output: {location_id, name, body, body_truncated, size, sha256} (sha256 of the bytes this answer was read from, the
    ``base_sha256`` a ``PUT`` of the same path takes).
    Raises: 404 unknown project, profile, location or a folder gone; 409 with
    ``{"code", "detail"}`` for target_unsafe or no_skill_md.
    """
    hit, root = await resolve_location(request, location_id, project_path, profile)
    try:
        body, truncated, size, sha256 = await asyncio.to_thread(read_location_skill_md_hashed, hit, root)
    except OverrideError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": exc.detail})
    return {
        "location_id": location_id, "name": hit["name"], "body": body, "body_truncated": truncated, "size": size,
        "sha256": sha256,
    }


@router.get("/sessions/{session_id}/skills", dependencies=[Depends(require_peer_sessions)])
async def get_session_skills(request: Request, session_id: str) -> Dict[str, Any]:
    """The skills one live session's agent really has (issue #1078).

    Description: resolves the session through ``get_session_info`` (a created
    id and an ``adopted:<tmux-name>`` id both work), reads the family from the
    WRAPPER and ``working_dir`` from the nested ``.session`` (gotcha 1), and
    the pane's own ``CLAUDE_CONFIG_DIR`` / ``CODEX_HOME`` one variable at a
    time. Read only. A family that is neither claude nor codex answers
    ``{"state": "unsupported"}`` with no ``skills`` key.
    Inputs: session_id (str) - a session row id.
    Output: see ``resolve_session_skills`` and ``docs/skills-manager.md``.
    Raises: HTTPException 404 unknown session; 409 ``remote_host`` for a far session.
    Example: GET /api/v1/sessions/adopted:cloude_x/skills -> {"state": "ok", ...}
    """
    manager = request.app.state.session_manager
    refuse_remote(manager, session_id, "the session skills read")
    info = await manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    session = info.session
    family = info.agent_family or session.agent_type
    home = Path.home()
    config_dir: Optional[str] = None
    codex_home = _codex_home(home)
    codex_from_pane = False
    if info.tmux_session and family in ("claude", "codex"):
        variable = "CLAUDE_CONFIG_DIR" if family == "claude" else "CODEX_HOME"
        pane = await read_pane_profile(manager._tmux_socket_name(), info.tmux_session, variable)
        if pane.readable and pane.value:
            if family == "claude":
                config_dir = pane.value
            else:
                codex_home, codex_from_pane = Path(pane.value).expanduser(), True
    return await asyncio.to_thread(
        resolve_session_skills,
        family=family,
        config_dir=config_dir,
        codex_home=codex_home,
        codex_from_pane=codex_from_pane,
        working_dir=session.working_dir,
        started=session.created_at,
        home=home,
        plugin_scope=discover_plugin_scope,
    )
