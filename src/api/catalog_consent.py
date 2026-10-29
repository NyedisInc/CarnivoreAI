
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import structlog
from fastapi import HTTPException, Request

from src.api.catalog_views import host_of
from src.core.skills.install_types import CONSENT_REQUIRED
from src.cplugs.host.install_gates import CplugFacts
from src.core.skills.kinds import KIND_CPLUG, KIND_MOD, KIND_PLUGIN, KIND_SKILL
from src.core.skills.manifest_rules import declares_script
from src.core.skills.plugin_safe_subset import (
    folder_declares_code,
    staged_has_script_members,
    staged_mcp_servers,
)
from src.core.skills.ledger_types import InstalledItem
from src.core.skills.manifest_preview import preview_manifest
from src.models.catalog import CatalogItem, ItemVersion
from src.models.catalog_contents import UpdateDiff
from src.models.catalog_api import (
    InstallConsent,
    InstalledUpdateRequest,
    InstallPreviewResponse,
    McpServerPreview,
    PreviewFile,
    UpdateConsent,
)

DIGEST_PREFIX_LENGTH = 12

logger = structlog.get_logger()


def preview_body(
    request: Request,
    *,
    item: CatalogItem,
    version: ItemVersion,
    staged: Any,
    plan_token: Optional[str],
    body_sha: Optional[str] = None,
) -> InstallPreviewResponse:
    services = request.app.state.services
    manifest = preview_manifest(staged.path, item.kind)
    key_id = version.sig.key_id
    scripts = list(staged.archive.script_members)
    return InstallPreviewResponse(
        body=manifest.skill_md_text,
        body_truncated=manifest.skill_md_truncated,
        files=[
            PreviewFile(path=entry.relpath, size=entry.size)
            for entry in manifest.files
        ],
        total_bytes=manifest.total_bytes,
        publisher=item.publisher,
        version=version.v,
        key_id=key_id,
        pinned=key_id == services.catalog.publisher_key_id,
        index_host=host_of(services.catalog.index_url()),
        digest=staged.digest,
        digest_prefix=staged.digest[:DIGEST_PREFIX_LENGTH],
        body_sha=body_sha,
        warnings=list(manifest.frontmatter_warnings),
        script_files=scripts,
        mcp_servers=(
            [McpServerPreview(**row) for row in staged_mcp_servers(staged.path)]
            if item.kind == KIND_PLUGIN
            else []
        ),
        requires_consent=version.scripts > 0
        or staged_plugin_declares_code(item.kind, staged.path),
        review=(
            None
            if version.review is None
            else version.review.model_dump(mode="json")
        ),
        plan_token=plan_token,
    )


def carries_scripts(version: ItemVersion) -> bool:
    return version.scripts > 0


def staged_plugin_declares_code(kind: str, staged_path: Path) -> bool:
    if kind == KIND_MOD:
        return True
    if kind == KIND_CPLUG:
        return True
    if kind == KIND_PLUGIN and declares_script(kind, staged_path):
        return True
    if kind in (KIND_SKILL, KIND_PLUGIN) and staged_has_script_members(staged_path):
        return True
    return folder_declares_code(staged_path, plugin=kind == KIND_PLUGIN)


def install_consent_satisfied(
    consent: Optional[Union[InstallConsent, UpdateConsent]],
    *,
    digest: str,
    body_sha: str,
) -> bool:
    if consent is None:
        return False
    if not consent.scripts:
        return False
    return consent.digest == digest and consent.body_sha == body_sha


def consent_carried(
    row: InstalledItem,
    body: InstalledUpdateRequest,
    body_sha: str,
    *,
    scripts_present: bool,
    digest: str,
) -> bool:
    if scripts_present:
        return install_consent_satisfied(
            body.consent, digest=digest, body_sha=body_sha
        )
    if row.consented_body_sha is not None and row.consented_body_sha == body_sha:
        return True
    return body.consent is not None and body.consent.body_sha == body_sha


def put_on_sheet(sheet: InstallPreviewResponse, facts: Any) -> InstallPreviewResponse:
    if isinstance(facts, CplugFacts):
        sheet.cplug_facts = facts.facts
        sheet.cplug_facts_sha = facts.sha
    elif facts is not None:
        sheet.mod_report = facts[0].model_dump(mode="json")
        sheet.mod_report_sha = facts[1]
        sheet.mod_flagged_ack_needed = facts[2]
        sheet.mod_settings_groups = facts[3]
    return sheet


def consent_sheet(
    request: Request,
    *,
    item: CatalogItem,
    version: ItemVersion,
    staged: Any,
    body_sha: str,
    detail: str,
    mod_facts: Any = None,
) -> InstallPreviewResponse:
    sheet = preview_body(
        request,
        item=item,
        version=version,
        staged=staged,
        plan_token=None,
        body_sha=body_sha,
    )
    sheet.code = CONSENT_REQUIRED
    sheet.detail = detail
    return put_on_sheet(sheet, mod_facts)


def consent_409(
    request: Request,
    item: CatalogItem,
    version: ItemVersion,
    staged: Any,
    body_sha: str,
    *,
    detail: Optional[str] = None,
    diff: Optional[UpdateDiff] = None,
    mod_facts: Any = None,
) -> HTTPException:
    wording = detail or (
        f"the {version.v} manifest is not the text this install was "
        "consented to; show it and send its body_sha back as consent"
    )
    sheet = consent_sheet(
        request,
        item=item,
        version=version,
        staged=staged,
        body_sha=body_sha,
        detail=wording,
        mod_facts=mod_facts,
    )
    sheet.diff = diff
    logger.info(
        "skill_consent_required",
        item_id=item.id,
        version=version.v,
        scripts=len(sheet.script_files),
    )
    return HTTPException(status_code=409, detail=sheet.model_dump(mode="json"))
