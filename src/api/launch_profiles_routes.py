
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.config import settings
from src.config.launch_profiles import LaunchProfile
from src.core import icon_registry
from src.core.agent_families import RESERVED_FAMILY_NAMES
from src.core.agent_wrappers import wrapper_scripts_dir
from src.core.byoai.contracts import to_connection
from src.core.db import DatastoreError, connect, db_path_for
from src.core.launch_profiles import check, share, usage
from src.core.launch_profiles.resolve import LaunchProfileNotFound, LaunchRequest, resolve_launch
from src.core.launch_profiles.store import LaunchProfileError, LaunchProfileStore, NotFound, StaleRevision
from src.core.launch_profiles.summary import summary_row

logger = structlog.get_logger()

router = APIRouter(prefix="/launch-profiles", tags=["launch-profiles"])


def _config_path() -> Path:
    return Path(settings.auth_config_file).expanduser()


def _store() -> LaunchProfileStore:
    return LaunchProfileStore(_config_path())


def _row(profile: LaunchProfile) -> Dict[str, Any]:
    return {**profile.model_dump(mode="json"), "summary": summary_row(profile)}


def _error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


async def _store_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        result = await run_in_threadpool(fn, *args, **kwargs)
    except NotFound as exc:
        raise _error(404, "not_found", str(exc))
    except StaleRevision as exc:
        raise _error(409, "stale_revision", str(exc))
    except LaunchProfileError as exc:
        raise _error(422, "invalid", str(exc))
    except (FileNotFoundError, ValueError) as exc:
        logger.error("launch_profiles_config_unreadable", error=str(exc))
        raise _error(500, "config_unreadable", "configuration is missing or unreadable")
    settings.drop_auth_config_cache()
    return result


def _usage(profile_id: str) -> Dict[str, int]:
    state_dir = Path(settings.get_state_dir())
    try:
        with closing(connect(db_path_for(state_dir), create=False)) as conn:
            return usage.count_references(conn, profile_id)
    except (DatastoreError, sqlite3.Error) as exc:
        raise usage.UsageUnknown(f"the datastore could not be read: {exc}") from exc


async def ensure_deletable(profile_id: str) -> None:
    try:
        counts = await run_in_threadpool(_usage, profile_id)
    except usage.UsageUnknown as exc:
        raise _error(503, "usage_unknown", f"which launches use this profile could not be read: {exc}")
    total = sum(counts.values())
    if total:
        listed = ", ".join(f"{n} {kind.replace('_', ' ')}" for kind, n in counts.items() if n)
        raise _error(409, "in_use", f"{profile_id} is still used by {listed}; move them to another launch profile first",
                     counts=counts, move_references=f"/api/v1/launch-profiles/{profile_id}/move-references")


def _find(profile_id: str) -> LaunchProfile:
    try:
        return _store().get(profile_id)
    except NotFound as exc:
        raise _error(404, "not_found", str(exc))
    except (FileNotFoundError, ValueError, LaunchProfileError) as exc:
        logger.error("launch_profiles_config_unreadable", error=str(exc))
        raise _error(500, "config_unreadable", "the launch profiles could not be read")


@router.get("", dependencies=[Depends(require_auth)])
async def list_profiles() -> Dict[str, Any]:
    """Every launch profile, in stored order, with the block's revision (echo it to write)."""
    block = await _store_call_read(_store().read)
    return {"revision": block.revision, "profiles": [_row(p) for p in block.profiles]}


async def _store_call_read(fn: Any) -> Any:
    try:
        return await run_in_threadpool(fn)
    except (FileNotFoundError, ValueError, LaunchProfileError) as exc:
        logger.error("launch_profiles_config_unreadable", error=str(exc))
        raise _error(500, "config_unreadable", "the launch profiles could not be read")


class ProfileWrite(BaseModel):
    """A create or replace: the whole profile and the revision the caller read (optional)."""

    model_config = ConfigDict(extra="forbid")

    profile: LaunchProfile
    expected_revision: Optional[int] = None


@router.post("", status_code=201, dependencies=[Depends(require_auth)])
async def create_profile(body: ProfileWrite) -> Dict[str, Any]:
    """Add a launch profile. 409 when the id exists, is a harness name, or the revision is stale."""
    profile = body.profile
    if profile.id in RESERVED_FAMILY_NAMES:
        raise _error(409, "reserved_id", f"{profile.id} is a harness name, not usable as a launch profile id")
    if any(p.id == profile.id for p in (await _store_call_read(_store().list))):
        raise _error(409, "exists", f"a launch profile named {profile.id} already exists")
    block = await _store_call(_store().put, profile, expected_revision=body.expected_revision)
    logger.info("launch_profile_created", profile_id=profile.id, harness=profile.harness)
    return {"revision": block.revision, "profile": _row(next(p for p in block.profiles if p.id == profile.id))}


@router.get("/{profile_id}", dependencies=[Depends(require_auth)])
async def get_profile(profile_id: str) -> Dict[str, Any]:
    """One launch profile. 404 when none has this id."""
    return {"profile": _row(_find(profile_id))}


@router.put("/{profile_id}", dependencies=[Depends(require_auth)])
async def replace_profile(profile_id: str, body: ProfileWrite) -> Dict[str, Any]:
    """Replace one profile's fields in place; ``profile.id`` must match. A default stays the default."""
    if body.profile.id != profile_id:
        raise _error(400, "id_mismatch", "the profile id cannot change; create a new profile instead")
    current = _find(profile_id)
    profile = body.profile.model_copy(update={"default": current.default or body.profile.default})
    block = await _store_call(_store().put, profile, expected_revision=body.expected_revision)
    logger.info("launch_profile_replaced", profile_id=profile_id, harness=profile.harness)
    return {"revision": block.revision, "profile": _row(next(p for p in block.profiles if p.id == profile_id))}


@router.delete("/{profile_id}", dependencies=[Depends(require_auth)])
async def delete_profile(profile_id: str, expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Remove a launch profile after the guard: 409 ``is_default`` or ``in_use`` (counts per kind), 503 ``usage_unknown``."""
    profile = _find(profile_id)
    if profile.default:
        raise _error(409, "is_default", f"{profile_id} is the {profile.harness} default; make another profile the default first")
    await ensure_deletable(profile_id)
    block = await _store_call(_store().delete, profile_id, expected_revision=expected_revision)
    logger.info("launch_profile_deleted", profile_id=profile_id, harness=profile.harness)
    return {"revision": block.revision, "removed": profile_id}


@router.post("/{profile_id}/default", dependencies=[Depends(require_auth)])
async def set_default(profile_id: str, expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Make this profile its harness's default (the others of that harness are unflagged)."""
    block = await _store_call(_store().set_default, profile_id, expected_revision=expected_revision)
    return {"revision": block.revision, "profiles": [summary_row(p) for p in block.profiles]}


class IconBody(BaseModel):
    """A profile's icon, alone. ``icon`` is required so an empty body is a 422; null is the harness mark."""

    model_config = ConfigDict(extra="forbid")

    icon: Optional[str] = Field(..., description="An id from the icon picker's registry, or null for the harness mark")
    expected_revision: Optional[int] = None


@router.put("/{profile_id}/icon", dependencies=[Depends(require_auth)])
async def set_icon(profile_id: str, body: IconBody) -> Dict[str, Any]:
    """Set or clear one profile's icon, validated against the picker's own list. Changes nothing else."""
    icon = body.icon or None
    if icon is not None:
        try:
            known = icon_registry.known_ids().accepts(icon)
        except icon_registry.IconRegistryUnavailable as exc:
            raise _error(503, icon_registry.UNAVAILABLE_CODE, str(exc))
        if not known:
            raise _error(400, "unknown_icon", f"unknown icon id {icon!r}")
    profile = _find(profile_id).model_copy(update={"icon": icon})
    block = await _store_call(_store().put, profile, expected_revision=body.expected_revision)
    return {"revision": block.revision, "profile": _row(next(p for p in block.profiles if p.id == profile_id))}


@router.get("/{profile_id}/usage", dependencies=[Depends(require_auth)])
async def profile_usage(profile_id: str) -> Dict[str, Any]:
    """Where a profile is referenced: a count per kind (sessions, blueprint members, project defaults, Time Machine points)."""
    _find(profile_id)
    try:
        counts = await run_in_threadpool(_usage, profile_id)
    except usage.UsageUnknown as exc:
        raise _error(503, "usage_unknown", f"which launches use this profile could not be read: {exc}")
    return {"profile_id": profile_id, "counts": counts, "total": sum(counts.values())}


class MoveBody(BaseModel):
    """Move every reference to another profile of the same harness."""

    model_config = ConfigDict(extra="forbid")

    to: str


def _move(profile_id: str, target: str) -> Dict[str, int]:
    state_dir = Path(settings.get_state_dir())
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        return usage.move_references(conn, profile_id, target)


@router.post("/{profile_id}/move-references", dependencies=[Depends(require_auth)])
async def move_references(profile_id: str, body: MoveBody) -> Dict[str, Any]:
    """Repoint every session row, blueprint member, project default and Time Machine point at another profile.

    Raises: 404 either id unknown; 409 ``harness_mismatch`` (a row's stored family would disagree); 503 when a
      reference kind cannot be read or written.
    """
    source, target = _find(profile_id), _find(body.to)
    if source.id == target.id:
        raise _error(400, "same_profile", "pick a different launch profile to move to")
    if source.harness != target.harness:
        raise _error(409, "harness_mismatch", f"{source.id} is {source.harness} and {target.id} is {target.harness}; move to a {source.harness} profile")
    try:
        moved = await run_in_threadpool(_move, profile_id, target.id)
    except (usage.UsageUnknown, OSError, sqlite3.Error, DatastoreError) as exc:
        raise _error(503, "move_failed", f"the references could not be moved: {exc}")
    return {"from": profile_id, "to": target.id, "moved": moved}


def _render_preview(profiles: List[LaunchProfile], profile_id: str, model: Optional[str]) -> Dict[str, Any]:
    try:
        auth = settings.load_auth_config()
        byoai = getattr(auth, "byoai", None)
        connections = tuple(to_connection(c) for c in byoai.connections) if byoai is not None else ()
        request = LaunchRequest(
            profiles=tuple(profiles), agent_type=profile_id, explicit=True, model=model,
            model_is_explicit=True,
            scripts_dir=wrapper_scripts_dir(str(settings.get_state_dir())), connections=connections,
        )
        plan = resolve_launch(request, "preview")
    except LaunchProfileNotFound as exc:
        raise _error(404, "not_found", str(exc))
    except (ValueError, NotImplementedError, LookupError) as exc:
        raise _error(422, "cannot_launch", str(exc))
    return {
        "profile_id": profile_id,
        "command": plan.command,
        "argv_tail": list(plan.argv_tail),
        "env_set": [{"name": n, "value": v} for n, v in plan.env_set],
        "env_unset": list(plan.env_unset),
        "secrets": [{"name": n, "keychain_ref": ref, "key_hint": plan.display.key_hint} for n, ref in plan.secret_refs],
        "script": plan.script_file.content if plan.script_file else None,
        "display": {"label": plan.display.label, "harness": plan.display.harness, "account": plan.display.account,
                    "model": plan.display.model, "permissions": plan.display.permissions,
                    "endpoint": plan.display.endpoint},
        "digest": plan.digest,
    }


@router.get("/{profile_id}/preview", dependencies=[Depends(require_auth)])
async def preview_profile(profile_id: str, model: Optional[str] = None) -> Dict[str, Any]:
    """A dry render of a SAVED profile: the exact command, env and secret rows (names, references, key hint).

    Never reads the Keychain and writes nothing (not even the custom command's script file).
    Raises: 404 no such profile; 422 ``cannot_launch`` with the resolver's reason.
    """
    _find(profile_id)
    profiles = list(await _store_call_read(_store().list))
    return _render_preview(profiles, profile_id, model)


class DraftPreview(BaseModel):
    """An unsaved profile to dry-render, and the model a launch would pass (for ``model: ask``)."""

    model_config = ConfigDict(extra="forbid")

    profile: LaunchProfile
    model: Optional[str] = None


@router.post("/preview", dependencies=[Depends(require_auth)])
async def preview_draft(body: DraftPreview) -> Dict[str, Any]:
    """A dry render of an UNSAVED profile (the editor's live preview): same answer as the saved route, nothing written.

    The draft replaces the stored profile of the same id (or is added when the id is new) for this render only.
    Raises: 422 ``cannot_launch`` (the resolver's reason) or a field error from the profile's own validation.
    """
    stored = [p for p in await _store_call_read(_store().list) if p.id != body.profile.id]
    return _render_preview([*stored, body.profile], body.profile.id, body.model)


async def _endpoint_check(profile: LaunchProfile) -> Dict[str, Any]:
    from src.api import ai_routes

    connection_id = profile.endpoint.connection_id or ""
    models: List[Any] = []
    try:
        listed = await ai_routes.connection_models(connection_id, cached_only=True)
        models = listed["models"] or (await ai_routes.connection_models(connection_id))["models"]
        model = profile.model.value if profile.model.mode == "fixed" else (models[0]["id"] if models else None)
        tested = await ai_routes.test_connection(connection_id, ai_routes.TestBody(capability="chat", model=model))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"detail": str(exc.detail)}
        return {"connection_id": connection_id, "ok": False, "error": detail.get("error", "failed"),
                "detail": str(detail.get("detail", ""))[:300], "models": len(models)}
    return {"connection_id": connection_id, "ok": bool(tested.get("ok")), "detail": str(tested.get("error") or "")[:300],
            "models": len(models)}


@router.post("/{profile_id}/check", dependencies=[Depends(require_auth)])
async def check_profile(profile_id: str) -> Dict[str, Any]:
    """Run the harness binary's ``--version`` (scrubbed env, no secrets, no ``before_launch``, 5 s) and, for a
    connection endpoint, the BYOAI connection test and model list. Always 200: a failure is ``status`` / ``ok: false``."""
    profile = _find(profile_id)
    body: Dict[str, Any] = {"profile_id": profile_id, "binary": await check.run_check(profile)}
    if profile.endpoint.mode == "connection":
        body["endpoint"] = await _endpoint_check(profile)
    return body


@router.get("/{profile_id}/export", dependencies=[Depends(require_auth)])
async def export_profile(profile_id: str):
    """One profile as a ``carnivore.launch_profile/1`` document, served as a download. Secrets are names and references only."""
    return JSONResponse(share.export_document(_find(profile_id)), headers={
        "Content-Disposition": f'attachment; filename="{profile_id}.launch-profile.json"', "Cache-Control": "no-store"})


async def _read_body(request: Request) -> Dict[str, Any]:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > share.MAX_DOCUMENT_BYTES:
        raise _error(413, "too_large", f"the document is larger than {share.MAX_DOCUMENT_BYTES} bytes")
    raw = await request.body()
    if len(raw) > share.MAX_DOCUMENT_BYTES:
        raise _error(413, "too_large", f"the document is larger than {share.MAX_DOCUMENT_BYTES} bytes")
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _error(400, "bad_body", "the body is not JSON")
    if not isinstance(body, dict):
        raise _error(400, "bad_body", "the body is not a JSON object")
    return body


def _document(body: Dict[str, Any]) -> LaunchProfile:
    try:
        return share.parse_document(body.get("document"))
    except share.ShareError as exc:
        raise _error(422, "invalid_document", str(exc))


@router.post("/import/preview", dependencies=[Depends(require_auth)])
async def preview_import(request: Request) -> Dict[str, Any]:
    """Validate a shared profile and show what it would run. Writes nothing.

    Body: ``{"document": <carnivore.launch_profile/1>}``. Output: the profile, every executable part, the digest to
    echo to import, and whether the id exists and whether its endpoint's connection exists here.
    """
    profile = _document(await _read_body(request))
    existing = {p.id: p for p in await _store_call_read(_store().list)}
    byoai = getattr(settings.load_auth_config(), "byoai", None)
    connection_ids = {c.id for c in byoai.connections} if byoai is not None else set()
    wanted = profile.endpoint.connection_id
    return {
        "profile": profile.model_dump(mode="json"),
        "sha256": share.profile_digest(profile),
        "parts": share.executable_parts(profile),
        "exists": profile.id in existing,
        "existing_is_default": bool(existing.get(profile.id) and existing[profile.id].default),
        "endpoint_connection_missing": bool(wanted and wanted not in connection_ids),
    }


@router.post("/import", dependencies=[Depends(require_auth)])
async def import_profile(request: Request) -> Dict[str, Any]:
    """Write a shared profile after the caller confirmed its exact digest.

    Body: ``{"document", "confirm_sha256", "replace": false}``. Raises: 409 ``digest_mismatch`` (not the digest of
    this profile), ``exists`` (id taken and ``replace`` false), ``reserved_id``; 422 a malformed document. The
    profile is never a default unless it replaced one.
    """
    body = await _read_body(request)
    profile = _document(body)
    replace_flag = body.get("replace", False)
    if not isinstance(replace_flag, bool):
        raise _error(422, "invalid", "replace must be true or false")
    if body.get("confirm_sha256") != share.profile_digest(profile):
        raise _error(409, "digest_mismatch", "confirm_sha256 does not match this profile; review it and confirm again")
    existing = {p.id: p for p in await _store_call_read(_store().list)}
    if profile.id in existing and not replace_flag:
        raise _error(409, "exists", f"a launch profile named {profile.id} already exists")
    default = bool(profile.id in existing and existing[profile.id].default)
    block = await _store_call(_store().put, profile.model_copy(update={"default": default}))
    logger.info("launch_profile_imported", profile_id=profile.id, replaced=profile.id in existing, sha256=share.profile_digest(profile))
    return {"revision": block.revision, "replaced": profile.id in existing,
            "profile": _row(next(p for p in block.profiles if p.id == profile.id))}
