
from __future__ import annotations

from typing import Any, List, Optional

import structlog
from fastapi import HTTPException
from starlette.requests import Request

from src.api.catalog_install_routes import _snapshot, preview_install, run_install
from src.api.catalog_install_support import resolve_item
from src.core.catalog.default_items import DEFAULT_ITEM_IDS
from src.core.mods import owner_state
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL
from src.models.catalog_api import InstallConsent, InstallRequest

logger = structlog.get_logger()


def boot_request(app: Any) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


async def install_defaults(request: Request, *, ids=DEFAULT_ITEM_IDS, state_dir: Optional[Any] = None) -> List[str]:
    installed: List[str] = []
    for item_id in ids:
        if owner_state.was_offered(item_id, state_dir=state_dir):
            continue
        try:
            snapshot = await _snapshot(request)
            resolve_item(snapshot, item_id)
        except HTTPException:
            logger.info("default_install_catalog_unavailable", item_id=item_id)
            continue
        owner_state.mark_offered(item_id, state_dir=state_dir)
        with request.app.state.services.catalog.ledger() as ledger:
            if ledger.find(item_id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH) is not None:
                continue
        try:
            body = InstallRequest(item_id=item_id, scope="global")
            preview = await preview_install(request, body)
            if (
                preview.mod_flagged_ack_needed
                or getattr(preview, "requires_warning_ack", False)
                or getattr(preview, "flagged", False)
            ):
                logger.warning("default_install_needs_owner_tick", item_id=item_id)
                continue
            consent = InstallConsent(digest=preview.digest, body_sha=preview.body_sha, scripts=True,
                                     mod_trust=True, mod_report_sha=preview.mod_report_sha or "")
            await run_install(request, InstallRequest(item_id=item_id, scope="global", plan_token=preview.plan_token,
                                                      consent=consent))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            logger.warning("default_install_refused", item_id=item_id, status=exc.status_code, code=str(detail.get("code", "")))
            continue
        logger.info("default_install_done", item_id=item_id)
        installed.append(item_id)
    return installed
