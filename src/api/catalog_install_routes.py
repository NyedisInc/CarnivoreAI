
from __future__ import annotations

import asyncio
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api import catalog_cplug_gates, catalog_mod_gates
from src.api.catalog_install_support import (
    apply_now,
    choice_views,
    claim_staged,
    refuse_cplug_scripts,
    discard_all,
    fetch_and_stage,
    plan,
    refuse_409,
    resolve_item,
    scope_arguments,
)
from src.api.catalog_theme_rules import (
    drop_theme_run_grant,
    refuse_unsupported_scope,
)
from src.api.catalog_loadout_install import install_members
from src.api.catalog_loadout_rules import (
    ensure_cplug_root,
    ensure_loadouts_root,
    is_loadout,
    loadout_view,
    member_previews,
    record_members,
    resolved_members,
    stored_member_views,
)
from src.api.catalog_consent import (
    put_on_sheet,
    carries_scripts,
    staged_plugin_declares_code,
    consent_409,
    install_consent_satisfied,
    preview_body,
)
from src.api.catalog_one_click import (
    REASON_NO_SHEET_PROOF,
    REASON_SCRIPTS,
    one_click_precheck,
    plan_needs_sheet,
    sheet_answer_for_refusal,
    sheet_required,
    staging_refusal_as_sheet,
)
from src.api.catalog_routes import refuse_empty
from src.api.catalog_installed_watch import annotate_watch
from src.api.catalog_views import installed_view
from src.core.catalog import install_reporter
from src.core.catalog.index_cache import IndexSnapshot
from src.core.skills.consent_via_ddl import (
    CONSENT_BLUEPRINT,
    CONSENT_ONE_CLICK,
    CONSENT_SHEET,
)
from src.core.skills.digest import hash_file
from src.core.skills.install_types import (
    ALREADY_INSTALLED,
    CONSENT_REQUIRED,
    NAME_TAKEN,
    InstallPlan,
    InstallRefusal,
)
from src.core.skills.installer import discard_staging
from src.core.skills.loadout_members import MEMBER_ALREADY_PRESENT, MEMBER_INSTALLED
from src.core.skills.ledger_types import AlreadyInstalled
from src.core.skills.kinds import KIND_CPLUG, KIND_MOD, manifest_name
from src.models.catalog_api import (
    InstallPreviewResponse,
    InstallRequest,
    InstalledItemView,
    InstalledListResponse,
)

logger = structlog.get_logger()

router = APIRouter(tags=["catalog"])


async def _snapshot(request: Request) -> IndexSnapshot:
    snapshot = await request.app.state.services.catalog.index_cache.get()
    refuse_empty(snapshot)
    return snapshot


@router.get(
    "/catalog/installed",
    response_model=InstalledListResponse,
    dependencies=[Depends(require_auth)],
)
async def list_installed(
    request: Request,
    scope: Optional[Literal["global", "project"]] = None,
    project_path: Optional[str] = None,
) -> InstalledListResponse:
    """Every skill this app installed, with the update badge joined on.

    ``scope`` keeps only rows at that scope; ``project_path`` keeps only the
    rows of that project (implying project scope) and MUST be a known
    project: it is resolved by the same rules an install's is
    (``resolve_project_path``), so an arbitrary directory is a 409
    ``project_path_invalid`` rather than a probe of the disk. With neither,
    every row, as before.

    The badge is computed against the HELD index, so this never triggers
    a fetch and never fails on one: an index this server has not got yet
    means no badge, which is the honest render of "cannot say".
    """
    services = request.app.state.services
    snapshot = services.catalog.index_cache.snapshot()
    resolved_project: Optional[str] = None
    if project_path is not None:
        if scope == "global":
            raise HTTPException(
                status_code=400, detail="a global filter takes no project_path"
            )
        scope, resolved_project = await scope_arguments(
            request,
            InstallRequest(
                item_id="filter/filter", scope="project", project_path=project_path
            ),
        )
    with services.catalog.ledger() as ledger:
        rows = ledger.list()
    if scope is not None:
        rows = [row for row in rows if row.scope == scope]
    if resolved_project is not None:
        rows = [row for row in rows if row.project_path == resolved_project]
    views = []
    for row in rows:
        view = installed_view(row, snapshot)
        if is_loadout(row.kind):
            members = stored_member_views(request, row.install_id)
            view.members = members
            view.complete = bool(members) and all(
                member.state != "refused" for member in members
            )
        views.append(view)
    await asyncio.to_thread(annotate_watch, services, rows, views)
    return InstalledListResponse(items=views)


@router.post(
    "/catalog/install/preview",
    response_model=InstallPreviewResponse,
    dependencies=[Depends(require_auth)],
)
async def preview_install(
    request: Request, body: InstallRequest
) -> InstallPreviewResponse:
    """Download, verify and extract an item, and describe what it would write.

    WRITES NOTHING OUTSIDE STAGING. A preview that produced an
    installable plan keeps its staged copy and names it in
    ``plan_token``; every other path discards it.

    Raises:
        HTTPException(404): the held index carries no such item.
        HTTPException(400): the scope and the project path disagree.
        HTTPException(409): a refusal, carrying ``code``. A
            ``name_taken`` carries this same preview body plus
            ``choices``, because the user is being offered a way on
            rather than told no. A script-bearing item is NOT refused
            here; it comes back with ``script_files`` and
            ``requires_consent``.
        HTTPException(502): the tarball could not be fetched.
    """
    services = request.app.state.services
    snapshot = await _snapshot(request)
    item, version = resolve_item(snapshot, body.item_id)
    scope, project_path = await scope_arguments(request, body)
    refuse_unsupported_scope(item, scope)

    if is_loadout(item.kind):
        await asyncio.to_thread(ensure_loadouts_root, request)
    elif item.kind == KIND_CPLUG:
        await asyncio.to_thread(ensure_cplug_root, request)

    unlocked = carries_scripts(version)
    staging, staged = await fetch_and_stage(
        request, item, version, allow_scripts=unlocked
    )
    keep = False
    try:
        verdict = await plan(
            request,
            item=item,
            version=version,
            staged=staged,
            scope=scope,
            project_path=project_path,
            choice=body.choice,
            allow_scripts=unlocked,
            harnesses=body.harnesses,
            create_roots=body.create_roots,
        )
        if isinstance(verdict, InstallRefusal) and verdict.code != NAME_TAKEN:
            raise refuse_409(verdict.code, verdict.detail)

        body_sha, _size = await asyncio.to_thread(
            hash_file, staged.path / manifest_name(item.kind)
        )

        mod_facts = (
            await catalog_mod_gates.gate_staged_mod(version, staged.path)
            if item.kind == KIND_MOD
            else await catalog_cplug_gates.gate_staged_cplug(request, item, staged.path, version)
            if item.kind == KIND_CPLUG
            else None
        )

        preview = preview_body(
            request,
            item=item,
            version=version,
            staged=staged,
            plan_token=None,
            body_sha=body_sha,
        )
        put_on_sheet(preview, mod_facts)
        if is_loadout(item.kind):
            preview.loadout_members = member_previews(
                request, resolved_members(request, item, staged, snapshot)
            )

        if isinstance(verdict, (InstallPlan, InstallRefusal)):
            held, expired = services.catalog.staged_plans.put(
                staging=staging,
                staged=staged,
                item_id=item.id,
                version=version.v,
                scope=scope,
                project_path=project_path,
            )
            await discard_all(expired)
            preview.plan_token = held.token
            keep = True

        if isinstance(verdict, InstallRefusal):
            preview.code = verdict.code
            preview.detail = verdict.detail
            preview.choices = choice_views(verdict)
            raise HTTPException(
                status_code=409, detail=preview.model_dump(mode="json")
            )
        return preview
    finally:
        if not keep:
            await asyncio.to_thread(discard_staging, staging)


@router.post(
    "/catalog/install",
    response_model=InstalledItemView,
    dependencies=[Depends(require_auth)],
)
async def install_item(
    request: Request, body: InstallRequest
) -> InstalledItemView:
    """``POST /catalog/install``: install one item, consent taken on the sheet or one-click.

    Delegates to :func:`run_install`; kept separate because a FastAPI handler
    cannot carry the keyword the blueprint launch passes.
    """
    return await run_install(request, body)


async def run_install(
    request: Request, body: InstallRequest, *, blueprint: bool = False
) -> InstalledItemView:
    services = request.app.state.services
    snapshot = await _snapshot(request)
    item, version = resolve_item(snapshot, body.item_id)
    scope, project_path = await scope_arguments(request, body)
    refuse_unsupported_scope(item, scope)

    one_click = body.one_click and not blueprint
    if one_click:
        reason = one_click_precheck(item, version, body)
        if reason is not None:
            raise sheet_required(reason)

    if is_loadout(item.kind):
        await asyncio.to_thread(ensure_loadouts_root, request)
    elif item.kind == KIND_CPLUG:
        await asyncio.to_thread(ensure_cplug_root, request)

    refuse_cplug_scripts(item, version)
    unlocked = carries_scripts(version)
    if unlocked and (body.consent is None or not body.consent.scripts):
        raise refuse_409(
            CONSENT_REQUIRED,
            f"{item.id!r} ships executable content; preview it, show the "
            "script list, and send the consent back with the digest and "
            "the body_sha the sheet reported",
        )

    claimed = await claim_staged(request, body, scope, project_path, version)
    if claimed is not None:
        staging, staged = claimed.staging, claimed.staged
    else:
        try:
            staging, staged = await fetch_and_stage(
                request, item, version, allow_scripts=unlocked
            )
        except HTTPException as exc:
            as_sheet = staging_refusal_as_sheet(exc) if one_click else None
            if as_sheet is not None:
                raise as_sheet from None
            raise

    cplug_reserved = False
    row_landed = False
    try:
        plugin_code = await asyncio.to_thread(
            staged_plugin_declares_code, item.kind, staged.path
        )
        needs_consent = unlocked or plugin_code
        mod_facts = (
            await catalog_mod_gates.gate_staged_mod(version, staged.path)
            if item.kind == KIND_MOD
            else await catalog_cplug_gates.gate_staged_cplug(request, item, staged.path, version)
            if item.kind == KIND_CPLUG
            else None
        )
        if one_click and plugin_code:
            raise sheet_required(REASON_SCRIPTS)
        if needs_consent:
            body_sha, _size = await asyncio.to_thread(
                hash_file, staged.path / manifest_name(item.kind)
            )
            if not install_consent_satisfied(
                body.consent, digest=staged.digest, body_sha=body_sha
            ):
                raise consent_409(
                    request,
                    item,
                    version,
                    staged,
                    body_sha,
                    detail=(
                        "the consent does not name the bytes that staged; "
                        "show this sheet and send its digest and body_sha back"
                    ),
                    mod_facts=mod_facts,
                )
            if item.kind == KIND_CPLUG:
                catalog_cplug_gates.check_cplug_consent(body.consent, mod_facts)
            elif mod_facts is not None:
                catalog_mod_gates.check_mod_consent(body.consent, mod_facts)

        verdict = await plan(
            request,
            item=item,
            version=version,
            staged=staged,
            scope=scope,
            project_path=project_path,
            choice=body.choice,
            allow_scripts=unlocked,
            harnesses=body.harnesses,
            create_roots=body.create_roots,
        )
        if one_click:
            reason = (
                sheet_answer_for_refusal(verdict)
                if isinstance(verdict, InstallRefusal)
                else plan_needs_sheet(verdict)
            )
            if reason is not None:
                raise sheet_required(reason)
        if isinstance(verdict, InstallRefusal):
            extra = (
                {"choices": [c.model_dump() for c in choice_views(verdict)]}
                if verdict.code == NAME_TAKEN
                else {}
            )
            raise refuse_409(verdict.code, verdict.detail, **extra)

        index_url = services.catalog.index_url()
        consent_via = (
            CONSENT_BLUEPRINT
            if blueprint
            else CONSENT_ONE_CLICK
            if one_click
            else CONSENT_SHEET
        )
        resolved = (
            resolved_members(request, item, staged, snapshot)
            if is_loadout(item.kind)
            else ()
        )
        if not blueprint and not one_click and claimed is None and not needs_consent:
            raise sheet_required(REASON_NO_SHEET_PROOF)
        if item.kind == KIND_MOD and verdict.replaces:
            await asyncio.to_thread(catalog_mod_gates.unregister_planned, verdict)
        if item.kind == KIND_CPLUG:
            cplug_reserved = await asyncio.to_thread(catalog_cplug_gates.reserve_install, request, item)
        try:
            row = await asyncio.to_thread(
                apply_now, request, verdict, index_url, consent_via
            )
            row_landed = True
        except AlreadyInstalled as exc:
            raise refuse_409(ALREADY_INSTALLED, str(exc))
        except OSError as exc:
            logger.error("skill_install_failed", item_id=item.id, error=str(exc))
            raise HTTPException(
                status_code=500,
                detail=f"the install could not be written: {exc}",
            )
    finally:
        await asyncio.to_thread(discard_staging, staging)
        if cplug_reserved and not row_landed:
            await asyncio.to_thread(catalog_cplug_gates.release_reservation, request, item)

    if row.kind == KIND_CPLUG:
        await asyncio.to_thread(catalog_cplug_gates.reload_and_push, request)

    registration = (
        await asyncio.to_thread(catalog_mod_gates.register_installed, request, row.install_id)
        if row.kind == KIND_MOD
        else None
    )

    if is_loadout(row.kind):
        outcomes = await install_members(
            request,
            resolved=resolved,
            consents=body.member_consents,
            index_url=index_url,
            snapshot=snapshot,
        )
        await asyncio.to_thread(record_members, request, row.install_id, outcomes)
        if all(o.state in (MEMBER_INSTALLED, MEMBER_ALREADY_PRESENT) for o in outcomes):
            for outcome in outcomes:
                install_reporter.schedule_for(services, outcome.item_id, outcome.version)
        logger.info(
            "loadout_installed",
            item_id=row.item_id,
            members=len(outcomes),
        )
        return loadout_view(row, snapshot, outcomes)

    await asyncio.to_thread(drop_theme_run_grant, request, row)

    install_reporter.schedule_for(services, row.item_id, row.version)

    logger.info(
        "skill_installed",
        item_id=row.item_id,
        scope=row.scope,
        version=row.version,
    )
    view = installed_view(row, snapshot)
    view.mod_registration = registration
    return view
