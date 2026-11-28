
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from src.api.auth import require_auth
from src.api.catalog_hosted_routes import _hosted, _relay
from src.api.catalog_rating_routes import _bearer
from src.api.skills_manager_routes import _inventory_now, _profiles
from src.core import theme_paths
from src.core.catalog import (
    publish_digest,
    publish_facts,
    publish_github,
    publish_plugin_sources,
    publish_prepare,
    publish_prepare_kinds,
    publish_sends,
    submission_preview,
    submissions_watch,
)
from src.core.skill_manager.types import SCOPE_PERSONAL
from src.core.skills.ledger_types import SCOPE_GLOBAL
from src.plugins.host import sideload
from src.plugins.host.peer_refusal import refuse_peer_token_writes
from src.plugins.sdk.manifest_v2 import has_v2_manifest
from src.models.catalog_publish import (
    ItemFactsResponse,
    OwnerPublishRequest,
    PublishAccountResponse,
    PublishHeroRequest,
    PublishablePreviewRequest,
    PublishableListResponse,
    PublishableSkill,
    PublishPreviewResponse,
    PublishSendRequest,
)
from src.models.catalog_submit import SubmissionFileView, SubmissionRefusalView

logger = structlog.get_logger()

_SUBMISSION_ID = re.compile(r"[0-9a-f]{32}")

router = APIRouter(tags=["catalog"])
cplug_owner_router = APIRouter(
    prefix="/cplug-owner",
    tags=["cplugs"],
    dependencies=[Depends(refuse_peer_token_writes), Depends(require_auth)],
)


async def _own_locations(request: Request) -> List[Dict[str, Any]]:
    themes = (
        await _own_theme_locations(request)
        + await _own_plugin_locations(request)
        + await _own_cplug_locations(request)
    )
    profiles = await asyncio.to_thread(_profiles, Path.home())
    if not profiles:
        return themes
    snapshot = await request.app.state.services.catalog.index_cache.get()
    inventory = await asyncio.to_thread(
        _inventory_now, request, profiles, None, None, snapshot
    )
    skills = [
        loc
        for group in inventory["skills"]
        for loc in group["locations"]
        if loc["scope"] == SCOPE_PERSONAL
        and not loc["read_only"]
        and loc["plugin"] is None
        and loc["managed"] is None
    ]
    return skills + themes


async def _installed_names(request: Request, kind: str) -> Optional[set]:
    def read() -> Optional[set]:
        try:
            with request.app.state.services.catalog.ledger() as ledger:
                return {i.name for i in ledger.list(scope=SCOPE_GLOBAL) if i.kind == kind}
        except (AttributeError, sqlite3.Error) as exc:
            logger.warning("publish_ledger_unreadable", kind=kind, error=str(exc))
            return None

    return await asyncio.to_thread(read)


async def _own_theme_locations(request: Request) -> List[Dict[str, Any]]:
    names = await _installed_names(request, "theme")
    if names is None:
        return []
    return await asyncio.to_thread(
        publish_prepare_kinds.own_theme_locations, theme_paths.existing_user_themes_dir(), names
    )


async def _own_plugin_locations(request: Request) -> List[Dict[str, Any]]:
    names = await _installed_names(request, "plugin")
    mod_names = await _installed_names(request, "mod")
    if names is None or mod_names is None:
        return []
    return await asyncio.to_thread(publish_plugin_sources.own_plugin_locations, names, mod_names)


async def _own_cplug_locations(request: Request) -> List[Dict[str, Any]]:
    state_dir = request.app.state.services.settings_reader.state_dir()
    sideloaded = await asyncio.to_thread(sideload.items, Path(state_dir))
    return await asyncio.to_thread(publish_prepare_kinds.own_cplug_locations, sideloaded)


async def _handle_of(request: Request) -> str:
    try:
        answer = await _hosted(request, "GET", "/me", bearer=await _bearer(request))
    except HTTPException as exc:
        logger.info("publish_handle_unavailable", status=exc.status_code)
        return ""
    handle = _relay(answer).get("handle")
    return handle if isinstance(handle, str) else ""


async def _resolve(request: Request, location: str) -> Dict[str, Any]:
    for loc in await _own_locations(request):
        if loc["location_id"] == location:
            return loc
    raise HTTPException(
        status_code=404,
        detail={"code": "unknown_location", "detail": "that skill is not in your list"},
    )


async def _prepare(request: Request, loc: Dict[str, Any], version: str) -> publish_prepare.Prepared:
    kind = loc.get("kind", "skill")
    try:
        if kind == "skill":
            return await asyncio.to_thread(publish_prepare.prepare, loc["path"], version)
        handle = await _handle_of(request) if kind == publish_prepare_kinds.KIND_CPLUG else ""
        return await asyncio.to_thread(publish_prepare_kinds.prepare_kind, kind, loc["path"], version, handle)
    except submission_preview.FolderUnreadable as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "folder_unreadable", "detail": str(exc)},
        ) from exc


def _sends(request: Request) -> publish_sends.PublishSends:
    return publish_sends.PublishSends(request.app.state.services.settings_reader.state_dir())


async def _record(request: Request, work: Any, event: str) -> None:
    try:
        await asyncio.to_thread(work)
    except (sqlite3.Error, OSError) as exc:
        logger.warning(event, error=str(exc))


def _keep_hero(request: Request, body: PublishHeroRequest, media_id: str) -> None:
    store = _sends(request)
    sha = ""
    if body.source == "yours":
        try:
            sha = store.save_image(base64.b64decode(body.image_base64, validate=True))
        except ValueError:
            sha = ""
    store.set_hero(kind=body.kind, name=body.name, source=body.source, media_submission_id=media_id, image_sha=sha)


async def _with_versions(locs: List[Dict[str, Any]]) -> List[Any]:
    versions = await asyncio.to_thread(
        lambda: [publish_facts.declared_version(loc.get("kind", "skill"), loc["path"]) for loc in locs]
    )
    return list(zip(locs, versions))


@router.get(
    "/catalog/publish/mine",
    response_model=PublishableListResponse,
    dependencies=[Depends(require_auth)],
)
async def publishable_skills(request: Request) -> PublishableListResponse:
    """Your skills: the local scan minus everything the catalog installed."""
    return PublishableListResponse(
        skills=[
            PublishableSkill(
                location=loc["location_id"],
                kind=loc.get("kind", "skill"),
                name=loc["name"],
                harness=loc["harness"],
                description=loc["description"],
                is_symlink=bool(loc["is_symlink"]),
                version=version,
            )
            for loc, version in await _with_versions(await _own_locations(request))
        ]
    )


@router.post(
    "/catalog/publish/preview",
    response_model=PublishPreviewResponse,
    dependencies=[Depends(require_auth)],
)
async def publish_preview(
    request: Request, body: PublishablePreviewRequest
) -> PublishPreviewResponse:
    """Preflight for one skill: files, refusals, lint, cost, compat, digest.

    TALKS TO NOBODY, except a cplug, which asks the catalog once for your publisher handle.

    Raises:
        HTTPException(404): ``unknown_location``.
        HTTPException(400): ``folder_unreadable``.
    """
    loc = await _resolve(request, body.location)
    prepared = await _prepare(request, loc, body.version)
    ok, summary = publish_facts.check_summary([r.code for r in prepared.refusals])
    await _record(
        request,
        lambda: _sends(request).record_check(
            location_id=body.location, version=prepared.version, ok=ok, summary=summary,
            grade=str(prepared.lint.get("grade", "")) if prepared.lint else "",
            files=len(prepared.members), bytes=prepared.total_bytes, digest=prepared.digest,
            findings=[{"code": r.code, "path": r.path} for r in prepared.refusals if r.path],
        ),
        "publish_check_record_failed",
    )
    return PublishPreviewResponse(
        location=body.location,
        kind=prepared.kind,
        name=prepared.name,
        version=prepared.version,
        file_count=len(prepared.members),
        total_bytes=prepared.total_bytes,
        files=[
            SubmissionFileView(path=path, size=len(content))
            for path, content in prepared.members
        ],
        refusals=[
            SubmissionRefusalView(code=r.code, detail=r.detail, path=r.path)
            for r in prepared.refusals
        ],
        script_files=list(prepared.script_files),
        warnings=list(prepared.warnings),
        lint=prepared.lint,
        cost={"description_tokens_est": loc["description_tokens_est"], "label": "est."},
        compat={"harness": loc["harness"], "compatibility": prepared.compatibility},
        digest=prepared.digest,
        can_send=not prepared.refusals,
    )


@router.post("/catalog/submissions", dependencies=[Depends(require_auth)])
async def send_submission(request: Request, body: PublishSendRequest) -> Dict[str, Any]:
    """Send one skill, theme or plugin for review, only if it is still what the preview showed.

    Description: resolve, re-read, refuse a refused folder (409
      ``folder_refused``) or a changed one (409 ``folder_changed``), then
      forward the bytes just digested to the hosted ``POST /v1/submissions``
      with the catalog token. The hosted answer and its refusals are relayed.
    Raises:
        HTTPException(404) ``unknown_location``; 400 ``folder_unreadable``;
        409 ``folder_changed`` or ``folder_refused``; 403 not signed in;
        502 catalog host unreachable; otherwise the host's own status.
    """
    if body.source_type == "github":
        pointer_arg = body.pointer or (body.location[7:] if body.location.startswith("github:") else None)
        prepared_gh = publish_github.prepare_github_publish(
            pointer=pointer_arg,
            repo=body.repo,
            tag=body.tag,
            commit_sha=body.commit_sha,
            subdir=body.subdir,
            kind=body.kind,
            name=body.name,
            version=body.version,
            default_kind=body.kind or "skill",
        )
        if prepared_gh.digest != body.digest:
            raise HTTPException(
                status_code=409,
                detail={"code": "folder_changed", "detail": "the submission changed after it was previewed; preview it again"},
            )
        bearer = await _bearer(request)
        upstream_body = publish_github.build_hosted_github_payload(prepared_gh)
        answer = await _hosted(request, "POST", "/submissions", json_body=upstream_body, bearer=bearer)
        logger.info("catalog_submission_sent", status=answer.status, source_type="github")
        sent = _relay(answer)
        submission_id = sent.get("submission_id")
        if isinstance(submission_id, str) and _SUBMISSION_ID.fullmatch(submission_id):
            await _record(
                request,
                lambda: _sends(request).record_send(
                    submission_id=submission_id,
                    location_id=prepared_gh.location_id,
                    harness="",
                    kind=prepared_gh.kind,
                    name=prepared_gh.name,
                    version=prepared_gh.version,
                    digest=prepared_gh.digest,
                    files={},
                ),
                "publish_send_record_failed",
            )
        submissions_watch.after_write(request)
        return sent

    loc = await _resolve(request, body.location)
    prepared = await _prepare(request, loc, body.version)
    if prepared.digest != body.digest:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "folder_changed",
                "detail": "the folder changed after it was previewed; preview it again",
            },
        )
    if prepared.refusals:
        raise HTTPException(
            status_code=409,
            detail={"code": "folder_refused", "detail": "this folder would be refused"},
        )
    bearer = await _bearer(request)
    is_v2 = (
        loc.get("kind") == publish_prepare_kinds.KIND_CPLUG
        and await asyncio.to_thread(has_v2_manifest, Path(loc["path"]))
    )
    upstream_body: Dict[str, Any] = {
        "kind": prepared.kind,
        "name": prepared.name,
        "version": prepared.version,
        "files": [
            {"path": path, "content_base64": base64.b64encode(content).decode("ascii")}
            for path, content in prepared.members
        ],
    }
    if is_v2:
        upstream_body["schema"] = 2
    answer = await _hosted(
        request,
        "POST",
        "/submissions",
        json_body=upstream_body,
        bearer=bearer,
    )
    logger.info("catalog_submission_sent", status=answer.status, files=len(prepared.members))
    sent = _relay(answer)
    submission_id = sent.get("submission_id")
    if isinstance(submission_id, str) and _SUBMISSION_ID.fullmatch(submission_id):
        await _record(
            request,
            lambda: _sends(request).record_send(
                submission_id=submission_id, location_id=body.location, harness=loc["harness"], kind=prepared.kind,
                name=prepared.name, version=prepared.version, digest=publish_digest.hosted_digest(prepared.members),
                files=publish_digest.file_map(prepared.members),
            ),
            "publish_send_record_failed",
        )
    submissions_watch.after_write(request)
    return sent


@router.post("/catalog/submissions/media", dependencies=[Depends(require_auth)])
async def send_hero_image(request: Request, body: PublishHeroRequest) -> Dict[str, Any]:
    """Send a hero image for an item you published or submitted, for review.

    Description: a thin relay to the hosted ``POST /v1/submissions/media`` with the
      user's catalog token. The hosted route verifies the publisher and the image;
      the image is re-encoded with our own encoder before it can enter the catalog.
    Raises: the host's own refusals (400 bad_image, image_size or image_ratio; 404
      unknown_item; 413; 429), 403 not signed in, 502 catalog host unreachable.
    """
    bearer = await _bearer(request)
    payload: Dict[str, Any] = {"kind": body.kind, "name": body.name}
    if body.role == "screenshot":
        payload["role"] = "screenshot"
        payload["action"] = body.action
        if body.slot is not None:
            payload["slot"] = body.slot
        if body.caption:
            payload["caption"] = body.caption
        if body.action != "remove":
            payload["image_base64"] = body.image_base64
    else:
        payload["image_base64"] = body.image_base64
    answer = await _hosted(
        request, "POST", "/submissions/media",
        json_body=payload,
        bearer=bearer,
    )
    logger.info("catalog_hero_sent", status=answer.status, role=body.role)
    sent = _relay(answer)
    media_id = sent.get("submission_id")
    if body.role == "hero":
        await _record(request, lambda: _keep_hero(request, body, media_id if isinstance(media_id, str) else ""), "publish_hero_record_failed")
    submissions_watch.after_write(request)
    return sent


@router.get("/catalog/submissions/mine", dependencies=[Depends(require_auth)])
async def my_submissions(request: Request, refresh: bool = False) -> Dict[str, Any]:
    """Your submissions and their states, from the server's cached copy of the hosted list.

    Description: ``submissions_watch`` owns the one hosted read and names the ``catalog_submissions``
      topic on a change, so any number of windows cost no extra hosted reads. A cache older than 60 s
      is served and refreshed once; ``refresh=true`` forces one hosted read, at most one per 10 s.
    Raises: 403 not signed in, 429 the host's daily read limit, 502 catalog host unreachable.
    """
    return await submissions_watch.watch_for(request).mine(submissions_watch.reader_for(request), force=refresh)


@router.get("/catalog/submissions/{submission_id}/report", dependencies=[Depends(require_auth)])
async def submission_report(submission_id: str, request: Request) -> Dict[str, Any]:
    """The check results of one of your own submissions (gate ids, results, finding codes), relayed from the hosted api."""
    if not _SUBMISSION_ID.fullmatch(submission_id):
        raise HTTPException(status_code=404, detail="no such submission")
    answer = await _hosted(request, "GET", f"/submissions/{submission_id}/report", bearer=await _bearer(request))
    return _relay(answer)


@router.get(
    "/catalog/publish/items/{location:path}",
    response_model=ItemFactsResponse,
    dependencies=[Depends(require_auth)],
)
async def publish_item_facts(request: Request, location: str) -> ItemFactsResponse:
    """What only this computer knows about one folder: files, license, grade, version, changes since the last send, records.

    TALKS TO NOBODY, except a cplug, which asks the catalog once for your publisher handle. The body holds
    relative paths only and no filesystem path. The folder is read as a send would read it, at the version of
    the newest send, else the declared one, else 1.0.0.

    Raises:
        HTTPException(404): ``unknown_location``.
        HTTPException(400): ``folder_unreadable``.
    """
    loc = await _resolve(request, location)
    store = _sends(request)
    sends = await asyncio.to_thread(store.sends_for, location)
    declared = await asyncio.to_thread(publish_facts.declared_version, loc.get("kind", "skill"), loc["path"])
    prepared = await _prepare(request, loc, (sends[0]["version"] if sends else "") or declared or "1.0.0")
    checks = await asyncio.to_thread(store.checks_for, location)
    return ItemFactsResponse(**await asyncio.to_thread(publish_facts.build, loc, prepared, sends, checks))


@router.get("/catalog/publish/images/{sha}", dependencies=[Depends(require_auth)])
async def publish_sent_image(request: Request, sha: str) -> Response:
    """The local copy of an image you sent as your own, by its sha256 (the facts route names it as ``hero_sha``).

    Description: the copy is made when the image is sent and sits in ``publish_images/`` beside the send
      database; a send made before copies were kept has none. TALKS TO NOBODY.
    Raises: HTTPException(404) ``no such image`` for a bad sha or a copy that is not kept.
    """
    data = await asyncio.to_thread(_sends(request).image_bytes, sha)
    if data is None:
        raise HTTPException(status_code=404, detail="no such image")
    kind = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else "application/octet-stream"
    return Response(content=data, media_type=kind, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=31536000, immutable"})


_HANDLE_CACHE_TTL_S = 120.0
_handle_cache: Dict[tuple[int, str], tuple[float, PublishAccountResponse]] = {}
_handle_inflight: Dict[tuple[int, str], "asyncio.Task[PublishAccountResponse]"] = {}


def clear_handle_cache(app_id: Optional[int] = None) -> None:
    if app_id is None:
        _handle_cache.clear()
    else:
        for k in [k for k in _handle_cache if k[0] == app_id]:
            _handle_cache.pop(k, None)


@router.get(
    "/catalog/handle",
    response_model=PublishAccountResponse,
    dependencies=[Depends(require_auth)],
)
async def publish_account(request: Request) -> PublishAccountResponse:
    """Who the catalog says you are and whether you hold a publisher handle (single-flight + 120s TTL cache, #3286)."""
    import hashlib as _hashlib  # noqa: PLC0415
    import time as _time  # noqa: PLC0415

    bearer = await _bearer(request)
    token_hash = _hashlib.sha256(bearer.encode("utf-8")).hexdigest()[:16] if bearer else ""
    key = (id(request.app), token_hash)
    now = _time.monotonic()
    hit = _handle_cache.get(key)
    if hit is not None and now < hit[0]:
        return hit[1]
    inflight = _handle_inflight.get(key)
    if inflight is not None and not inflight.done():
        return await asyncio.shield(inflight)

    async def _fetch() -> PublishAccountResponse:
        answer = await _hosted(request, "GET", "/me", bearer=bearer)
        body = _relay(answer)
        handle = body.get("handle") if isinstance(body.get("handle"), str) else ""
        provider: Optional[str] = body.get("provider") if isinstance(body.get("provider"), str) else None
        resp = PublishAccountResponse(
            provider=provider,
            login=body.get("login") if isinstance(body.get("login"), str) else None,
            handle=handle,
            handle_status=body.get("handle_status") if isinstance(body.get("handle_status"), str) else "",
            can_claim=not handle,
            registered=body.get("registered") is True,
            terms_version=body.get("terms_version") if isinstance(body.get("terms_version"), str) else "",
            terms_url=body.get("terms_url") if isinstance(body.get("terms_url"), str) else "",
            terms_accepted=body.get("terms_accepted") if isinstance(body.get("terms_accepted"), str) else "",
            news_opt_in=body.get("news_opt_in") if isinstance(body.get("news_opt_in"), bool) else None,
            notify_replies=body.get("notify_replies") if isinstance(body.get("notify_replies"), bool) else None,
        )
        _handle_cache[key] = (_time.monotonic() + _HANDLE_CACHE_TTL_S, resp)
        return resp

    task = asyncio.create_task(_fetch())
    _handle_inflight[key] = task
    try:
        return await asyncio.shield(task)
    finally:
        if _handle_inflight.get(key) is task:
            _handle_inflight.pop(key, None)


@cplug_owner_router.post("/publish")
async def owner_publish(request: Request, body: OwnerPublishRequest) -> Dict[str, Any]:
    """Preview (``dry_run=True``) or submit a local v2 plugin directory or GitHub ``owner/repo@tag`` to Warez."""
    if body.source_type == "github" and not body.path:
        prepared_gh = publish_github.prepare_github_publish(
            pointer=body.pointer,
            repo=body.repo,
            tag=body.tag,
            commit_sha=body.commit_sha,
            subdir=body.subdir,
            kind=body.kind,
            name=body.name,
            version=body.version,
            default_kind=publish_prepare_kinds.KIND_CPLUG,
        )
        await _handle_of(request)
        await _record(
            request,
            lambda: _sends(request).record_check(
                location_id=prepared_gh.location_id,
                version=prepared_gh.version,
                ok=True,
                summary="clean",
                grade="",
                files=0,
                bytes=0,
                digest=prepared_gh.digest,
                findings=[],
            ),
            "publish_check_record_failed",
        )
        preview = PublishPreviewResponse(
            location=prepared_gh.location_id,
            kind=prepared_gh.kind,
            name=prepared_gh.name,
            version=prepared_gh.version,
            file_count=0,
            total_bytes=0,
            files=[],
            refusals=[],
            lint={},
            cost={"description_tokens_est": 0, "label": "est."},
            compat={"harness": "", "compatibility": None},
            digest=prepared_gh.digest,
            can_send=True,
            source_type="github",
            git_pointer=prepared_gh.pointer,
            commit_sha=prepared_gh.commit_sha,
        )
        if body.dry_run:
            return preview.model_dump(mode="json")
        if body.digest != prepared_gh.digest:
            raise HTTPException(
                status_code=409,
                detail={"code": "folder_changed", "detail": "the submission changed after it was previewed; preview it again"},
            )
        bearer = await _bearer(request)
        upstream_body = publish_github.build_hosted_github_payload(prepared_gh)
        answer = await _hosted(request, "POST", "/submissions", json_body=upstream_body, bearer=bearer)
        logger.info("cplug_owner_submission_sent", status=answer.status, source_type="github")
        sent = _relay(answer)
        submission_id = sent.get("submission_id")
        if isinstance(submission_id, str) and _SUBMISSION_ID.fullmatch(submission_id):
            await _record(
                request,
                lambda: _sends(request).record_send(
                    submission_id=submission_id,
                    location_id=prepared_gh.location_id,
                    harness="",
                    kind=prepared_gh.kind,
                    name=prepared_gh.name,
                    version=prepared_gh.version,
                    digest=prepared_gh.digest,
                    files={},
                ),
                "publish_send_record_failed",
            )
        submissions_watch.after_write(request)
        return sent

    if not body.path:
        raise HTTPException(
            status_code=422,
            detail={"code": "source_missing", "detail": "give the absolute path of a folder (not a link)"},
        )
    folder = Path(body.path)
    if not folder.is_absolute() or folder.is_symlink() or not folder.is_dir():
        raise HTTPException(
            status_code=422,
            detail={"code": "source_missing", "detail": "give the absolute path of a folder (not a link)"},
        )
    real_folder = os.path.realpath(folder)
    handle = await _handle_of(request)
    ver = (
        body.version
        or (await asyncio.to_thread(publish_facts.declared_version, publish_prepare_kinds.KIND_CPLUG, real_folder))
        or "1.0.0"
    )
    try:
        prepared = await asyncio.to_thread(
            publish_prepare_kinds.prepare_kind,
            publish_prepare_kinds.KIND_CPLUG,
            real_folder,
            ver,
            handle,
        )
    except submission_preview.FolderUnreadable as exc:
        logger.warning("cplug_owner_folder_unreadable", error=str(exc))
        raise HTTPException(
            status_code=400,
            detail={"code": "folder_unreadable", "detail": "the folder could not be read"},
        ) from exc

    prepared_gh = None
    eff_digest = prepared.digest
    if body.source_type == "github":
        prepared_gh = publish_github.prepare_github_publish(
            pointer=body.pointer,
            repo=body.repo,
            tag=body.tag,
            commit_sha=body.commit_sha,
            subdir=body.subdir,
            kind=body.kind or prepared.kind,
            name=body.name or prepared.name,
            version=prepared.version,
            default_kind=publish_prepare_kinds.KIND_CPLUG,
        )
        eff_digest = hashlib.sha256(f"{prepared.digest}:{prepared_gh.digest}".encode("utf-8")).hexdigest()

    location_id = f"cplug:{prepared.name}"
    ok, summary = publish_facts.check_summary([r.code for r in prepared.refusals])
    await _record(
        request,
        lambda: _sends(request).record_check(
            location_id=location_id,
            version=prepared.version,
            ok=ok,
            summary=summary,
            grade=str(prepared.lint.get("grade", "")) if prepared.lint else "",
            files=len(prepared.members),
            bytes=prepared.total_bytes,
            digest=eff_digest,
            findings=[{"code": r.code, "path": r.path} for r in prepared.refusals if r.path],
        ),
        "publish_check_record_failed",
    )
    preview = PublishPreviewResponse(
        location=location_id,
        kind=prepared.kind,
        name=prepared.name,
        version=prepared.version,
        file_count=len(prepared.members),
        total_bytes=prepared.total_bytes,
        files=[SubmissionFileView(path=path, size=len(content)) for path, content in prepared.members],
        refusals=[SubmissionRefusalView(code=r.code, detail=r.detail, path=r.path) for r in prepared.refusals],
        script_files=list(prepared.script_files),
        warnings=list(prepared.warnings),
        lint=prepared.lint,
        cost={"description_tokens_est": 0, "label": "est."},
        compat={"harness": "", "compatibility": prepared.compatibility},
        digest=eff_digest,
        can_send=not prepared.refusals,
        source_type="github" if prepared_gh else "upload",
        git_pointer=prepared_gh.pointer if prepared_gh else "",
        commit_sha=prepared_gh.commit_sha if prepared_gh else "",
    )
    if body.dry_run:
        return preview.model_dump(mode="json")

    if body.digest != eff_digest:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "folder_changed",
                "detail": "the folder changed after it was previewed; preview it again",
            },
        )
    if prepared.refusals:
        raise HTTPException(
            status_code=409,
            detail={"code": "folder_refused", "detail": "this folder would be refused"},
        )
    bearer = await _bearer(request)
    is_v2 = await asyncio.to_thread(has_v2_manifest, Path(real_folder))
    encoded_files = [
        {"path": path, "content_base64": base64.b64encode(content).decode("ascii")}
        for path, content in prepared.members
    ]
    if prepared_gh is not None:
        upstream_body = publish_github.build_hosted_github_payload(prepared_gh, files=encoded_files, is_v2=is_v2)
    else:
        upstream_body = {
            "kind": prepared.kind,
            "name": prepared.name,
            "version": prepared.version,
            "files": encoded_files,
        }
        if is_v2:
            upstream_body["schema"] = 2
    answer = await _hosted(request, "POST", "/submissions", json_body=upstream_body, bearer=bearer)
    logger.info("cplug_owner_submission_sent", status=answer.status, files=len(prepared.members), schema=2 if is_v2 else 1)
    sent = _relay(answer)
    submission_id = sent.get("submission_id")
    if isinstance(submission_id, str) and _SUBMISSION_ID.fullmatch(submission_id):
        await _record(
            request,
            lambda: _sends(request).record_send(
                submission_id=submission_id,
                location_id=location_id,
                harness="",
                kind=prepared.kind,
                name=prepared.name,
                version=prepared.version,
                digest=publish_digest.hosted_digest(prepared.members),
                files=publish_digest.file_map(prepared.members),
            ),
            "publish_send_record_failed",
        )
    submissions_watch.after_write(request)
    return sent
