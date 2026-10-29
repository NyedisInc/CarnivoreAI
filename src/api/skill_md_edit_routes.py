
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from src.api.auth import require_auth
from src.api.skills_manager_routes import resolve_location
from src.core import session_change_notice
from src.core.resource_push import notifier
from src.core.resource_push.topics import LOCAL_SKILLS
from src.core.skill_manager.skill_md_edit import MAX_EDIT_BYTES, StaleBase, file_sha256, restore_version, save_edit, target_path
from src.core.skill_manager.skill_md_versions import DB_NAME, NOTE_MAX, SkillMdVersionStore
from src.core.skill_manager.types import OverrideError
from src.models.websocket import WSMessageType

logger = structlog.get_logger()
router = APIRouter(tags=["skills"])
_BASE = "/skills/locations/{location_id}/skill-md"
MAX_SAVE_BODY = MAX_EDIT_BYTES * 6 + 4096


class SkillMdSave(BaseModel):
    """Body of the save: the new text, the sha256 it was edited from, an optional note."""

    content: str
    base_sha256: str = Field(min_length=64, max_length=64)
    note: str = Field(default="", max_length=NOTE_MAX)


class SkillMdRestore(BaseModel):
    """Body of the restore: the sha256 of the file the caller last saw."""

    base_sha256: str = Field(min_length=64, max_length=64)


def _store(request: Request) -> SkillMdVersionStore:
    return SkillMdVersionStore(Path(request.app.state.services.settings_reader.state_dir()) / DB_NAME)


async def _bounded_save_body(request: Request) -> SkillMdSave:
    too_large = HTTPException(status_code=413, detail={"code": "too_large", "detail": f"SKILL.md is capped at {MAX_EDIT_BYTES} bytes"})
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_SAVE_BODY:
        raise too_large
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_SAVE_BODY:
            raise too_large
    try:
        return SkillMdSave.model_validate_json(bytes(raw))
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False, include_input=False))


def _refuse(exc: OverrideError) -> Any:
    detail: Dict[str, Any] = {"code": exc.code, "detail": exc.detail}
    if isinstance(exc, StaleBase):
        detail["current_sha256"] = exc.current_sha256
        return JSONResponse(status_code=409, content={"detail": detail, "current_sha256": exc.current_sha256})
    raise HTTPException(status_code=exc.status, detail=detail)


def _wrote(request: Request, hit: Dict[str, Any], action: str) -> None:
    logger.info("skill_md_written", location_id=hit["location_id"], harness=hit["harness"], action=action)
    session_change_notice.publish(
        request.app.state, {"type": WSMessageType.SKILLS_CHANGED, "harness": hit["harness"], "file": "skill-md"}
    )
    notifier.notify(LOCAL_SKILLS)


@router.put(_BASE, dependencies=[Depends(require_auth)])
async def put_skill_md(
    request: Request, location_id: str, project_path: Optional[str] = None, profile: Optional[str] = None
) -> Any:
    """Save new SKILL.md text; it becomes the newest version, carrying the note.

    Inputs: location_id; JSON ``{content, base_sha256, note?}`` (read with a size bound: 413 ``too_large``
    before it is parsed); query ``project_path?``, ``profile?``.
    Output: {sha256, version_id} (the new file's hash; the version that holds the NEW text and its note).
    Raises: 404 unknown location or folder gone; 403 ``read_only``; 409 ``stale`` (with ``current_sha256``),
    ``target_unsafe``, ``no_skill_md``, ``too_large_to_edit``; 413 ``too_large``; 422 ``secret_detected`` / ``not_utf8``.
    Example: PUT .../skill-md {"content": "...", "base_sha256": "<from the GET>"}
    """
    body = await _bounded_save_body(request)
    hit, root = await resolve_location(request, location_id, project_path, profile)
    try:
        sha256, version_id = await asyncio.to_thread(save_edit, _store(request), hit, root, body.content, body.base_sha256, body.note.strip())
    except OverrideError as exc:
        return _refuse(exc)
    _wrote(request, hit, "edit")
    return {"sha256": sha256, "version_id": version_id}


@router.get(_BASE + "/versions", dependencies=[Depends(require_auth)])
async def list_skill_md_versions(
    request: Request, location_id: str, project_path: Optional[str] = None, profile: Optional[str] = None
) -> Any:
    """The saved versions of one SKILL.md, newest first (at most 50 are kept).

    Output: {versions: [{id, created_at, note, sha256, size, lines, action, redacted}], current: {same fields} | null};
    ``action`` is what made that content (``edit``, ``restore``, or ``baseline`` for the text a first save replaced).
    ``current`` is the newest version when it is the file on disk now (it carries the note typed with that save);
    ``versions`` then holds only the OLDER ones. When the file was changed outside this route, ``current`` is null
    and ``versions`` lists everything.
    Raises: 404 unknown location; 409 ``target_unsafe`` / ``no_skill_md``.
    Example: GET .../skill-md/versions -> {"versions": [{"id": 3, ...}]}
    """
    hit, root = await resolve_location(request, location_id, project_path, profile)
    try:
        path = await asyncio.to_thread(target_path, hit, root, write=False)
    except OverrideError as exc:
        return _refuse(exc)
    versions = await asyncio.to_thread(_store(request).list, path)
    try:
        on_disk = await asyncio.to_thread(file_sha256, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "gone", "detail": "that SKILL.md is no longer there"})
    if versions and versions[0]["sha256"] == on_disk:
        return {"versions": versions[1:], "current": versions[0]}
    return {"versions": versions, "current": None}


@router.get(_BASE + "/versions/{version_id}", dependencies=[Depends(require_auth)])
async def get_skill_md_version(
    request: Request, location_id: str, version_id: int, project_path: Optional[str] = None, profile: Optional[str] = None
) -> Any:
    """The text of one saved version. Output: {content, sha256}. Raises: 404 ``unknown_version`` or location.

    Example: GET .../skill-md/versions/3 -> {"content": "...", "sha256": "..."}
    """
    hit, root = await resolve_location(request, location_id, project_path, profile)
    try:
        path = await asyncio.to_thread(target_path, hit, root, write=False)
    except OverrideError as exc:
        return _refuse(exc)
    found = await asyncio.to_thread(_store(request).get, path, version_id)
    if found is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_version", "detail": "no such saved version of this file"})
    if found[2]:
        raise HTTPException(status_code=409, detail={"code": "version_redacted", "detail": "that version held a credential, so its text was not kept"})
    return {"content": found[0].decode("utf-8", errors="replace"), "sha256": found[1]}


@router.delete(_BASE + "/versions/{version_id}", dependencies=[Depends(require_auth)])
async def delete_skill_md_version(
    request: Request, location_id: str, version_id: int, project_path: Optional[str] = None, profile: Optional[str] = None
) -> Any:
    """Delete one saved version of this SKILL.md. Output: {deleted: true}. Raises: 404 ``unknown_version`` or location.

    Example: DELETE .../skill-md/versions/3 -> {"deleted": true}
    """
    hit, root = await resolve_location(request, location_id, project_path, profile)
    try:
        path = await asyncio.to_thread(target_path, hit, root, write=False)
    except OverrideError as exc:
        return _refuse(exc)
    if not await asyncio.to_thread(_store(request).delete, path, version_id):
        raise HTTPException(status_code=404, detail={"code": "unknown_version", "detail": "no such saved version of this file"})
    return {"deleted": True}


@router.post(_BASE + "/versions/{version_id}/restore", dependencies=[Depends(require_auth)])
async def restore_skill_md_version(
    request: Request, location_id: str, version_id: int, body: SkillMdRestore,
    project_path: Optional[str] = None, profile: Optional[str] = None,
) -> Any:
    """Write an older version back; the current file is kept as a new version first, so this can be undone.

    Inputs: JSON ``{base_sha256}``. Output: {sha256, version_id} (the version that holds the file just replaced).
    Raises: as the save, plus 404 ``unknown_version``.
    Example: POST .../skill-md/versions/3/restore {"base_sha256": "<current>"}
    """
    hit, root = await resolve_location(request, location_id, project_path, profile)
    try:
        sha256, new_id = await asyncio.to_thread(restore_version, _store(request), hit, root, version_id, body.base_sha256)
    except OverrideError as exc:
        return _refuse(exc)
    _wrote(request, hit, "restore")
    return {"sha256": sha256, "version_id": new_id}
