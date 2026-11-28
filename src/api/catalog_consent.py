
from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, List, Optional, Union

import structlog
from fastapi import HTTPException, Request

from src.api.catalog_views import host_of, is_version_flagged, warning_reasons_for_version
from src.core.skills.install_types import CONSENT_REQUIRED
from src.plugins.host import owner_switch
from src.plugins.host.install_gates import CplugFacts
from src.plugins.runtime.supervisor import safe_mode_from_env
from src.core.skills.code_gate import staged_plugin_declares_code
from src.core.skills.kinds import KIND_CPLUG, KIND_PLUGIN
from src.core.skills.plugin_safe_subset import staged_mcp_servers
from src.core.skills.ledger_types import InstalledItem
from src.core.skills.manifest_preview import preview_manifest
from src.models.catalog import CatalogItem, ItemVersion
from src.models.catalog_contents import UpdateDiff
from src.models.catalog_api import (
    InstallConsent,
    InstalledUpdateRequest,
    InstallPreviewResponse,
    McpServerPreview,
    PermissionDiffView,
    PreviewFile,
    UpdateConsent,
)

DIGEST_PREFIX_LENGTH = 12

logger = structlog.get_logger()


def _cplug_runtime_active(request: Request) -> bool:
    app_state = getattr(getattr(request, "app", None), "state", None)
    live = getattr(app_state, "sidecar_runtime", None)
    if live is not None and hasattr(live, "safe_mode"):
        return not any(live.safe_mode().values())
    services = getattr(app_state, "services", None)
    reader = getattr(services, "settings_reader", None)
    if reader is None:
        return False
    return owner_switch.read(reader.state_dir()) and not safe_mode_from_env()


def _warning_reasons_for_version(version: ItemVersion) -> Optional[list[str]]:
    return warning_reasons_for_version(version)


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
        runtime_active=_cplug_runtime_active(request) if item.kind == KIND_CPLUG else None,
        flagged=bool(
            getattr(version, "requires_warning_ack", False)
            or (version.review is not None and version.review.verdict == "flagged")
        ),
        requires_warning_ack=bool(
            getattr(version, "requires_warning_ack", False)
            or (version.review is not None and version.review.verdict == "flagged")
        ),
        warning_reasons=_warning_reasons_for_version(version),
        provenance=(
            version.provenance.model_dump(mode="json")
            if getattr(version, "provenance", None) is not None
            else None
        ),
        manifest_schema=getattr(version, "manifest_schema", None),
    )


def carries_scripts(version: ItemVersion) -> bool:
    return version.scripts > 0


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


_MAX_RELEASE_NOTES_CHARS = 2400


def extract_release_notes(staged_path: Any, version: str) -> Optional[str]:
    root = Path(staged_path) if staged_path is not None else None
    if root is None or not root.is_dir():
        return None
    manifest_file = root / "carnivore.toml"
    if manifest_file.is_file():
        try:
            data = tomllib.loads(manifest_file.read_text(encoding="utf-8", errors="replace"))
            raw = data.get("release_notes") or data.get("changelog")
            if isinstance(raw, list):
                joined = "\n".join(f"- {str(item).strip()}" for item in raw if str(item).strip())
                if joined:
                    return joined[:_MAX_RELEASE_NOTES_CHARS]
            elif isinstance(raw, str) and raw.strip():
                return raw.strip()[:_MAX_RELEASE_NOTES_CHARS]
        except (OSError, tomllib.TOMLDecodeError):
            pass

    ver_clean = (version or "").strip().lstrip("vV")
    ver_re = re.compile(rf"^#{{1,3}}\s+\[?v?{re.escape(ver_clean)}\]?(?:\b|\s|$)", re.IGNORECASE) if ver_clean else None
    for name in ("RELEASE_NOTES.md", "CHANGELOG.md", "changelog.md", "release_notes.md"):
        candidate = root / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        lines = text.splitlines()
        if ver_re is not None:
            start = next((i for i, ln in enumerate(lines) if ver_re.match(ln.strip())), None)
            if start is not None:
                section: List[str] = []
                for ln in lines[start + 1 :]:
                    if re.match(r"^#{1,3}\s+", ln.strip()):
                        break
                    section.append(ln)
                body = "\n".join(section).strip()
                if body:
                    return body[:_MAX_RELEASE_NOTES_CHARS]
        if name.lower().startswith("release_notes"):
            return text[:_MAX_RELEASE_NOTES_CHARS]
    return None


def consent_409(
    request: Request,
    item: CatalogItem,
    version: ItemVersion,
    staged: Any,
    body_sha: str,
    *,
    detail: Optional[str] = None,
    diff: Optional[UpdateDiff] = None,
    permission_diff: Optional[Any] = None,
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
    sheet.release_notes = extract_release_notes(getattr(staged, "path", None), version.v)
    if permission_diff is not None:
        raw_diff = (
            permission_diff.as_dict()
            if hasattr(permission_diff, "as_dict")
            else permission_diff
        )
        sheet.permission_diff = PermissionDiffView.model_validate(raw_diff)
    if is_version_flagged(version):
        sheet.flagged = True
        sheet.requires_warning_ack = True
        if sheet.warning_reasons is None:
            sheet.warning_reasons = warning_reasons_for_version(version)
        if sheet.review is None and getattr(version, "review", None) is not None:
            sheet.review = version.review.model_dump(mode="json")
    logger.info(
        "skill_consent_required",
        item_id=item.id,
        version=version.v,
        scripts=len(sheet.script_files),
    )
    return HTTPException(status_code=409, detail=sheet.model_dump(mode="json"))
