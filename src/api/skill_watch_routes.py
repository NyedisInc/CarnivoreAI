
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request

from src.api.auth import require_auth
from src.api.catalog_install_support import refuse_409
from src.api.catalog_installed_routes import apply_version
from src.api.catalog_installed_support import row_now, stale_409
from src.api.catalog_installed_watch import annotate_watch
from src.api.catalog_routes import refuse_empty
from src.api.catalog_views import find_item, installed_view
from src.core.skill_fires.tally import default_store
from src.core.catalog.revocation import version_subject
from src.core.catalog.verify_types import KEY_UNTRUSTED, VERSION_REVOKED
from src.core.skill_watch.autopsy import MAX_DAYS, build_autopsy
from src.core.skill_watch.attribution import SkillAttribution
from src.models.catalog_api import InstalledItemView, InstalledUpdateRequest
from src.models.skill_watch import ForkRequest, SkillAutopsy

router = APIRouter(tags=["skills"])

RESTORE_UNAVAILABLE = "restore_unavailable"
RESTORE_MISSING = "restore_missing"


def _autopsy_now(request: Request, name: str, days: int) -> dict:
    return build_autopsy(name, days, default_store(), datetime.now(timezone.utc),
                         attribution=SkillAttribution(request.app.state.services))


def _set_forked(services, install_id: str, forked: bool) -> None:
    with services.catalog.ledger() as ledger:
        ledger.set_forked(install_id, forked)


def _restorable(request: Request, row) -> bool:
    with request.app.state.services.catalog.ledger() as ledger:
        paths = [t.path for t in ledger.targets(row.install_id)]
    return bool(paths) and all(os.path.lexists(p) for p in paths)


@router.get("/skills/{name}/autopsy", response_model=SkillAutopsy,
            dependencies=[Depends(require_auth)])
async def get_skill_autopsy(request: Request, name: str,
                            days: int = Query(30, ge=1, le=MAX_DAYS)) -> SkillAutopsy:
    """What happened after this skill fired on this mac, over the last ``days`` days.

    Inputs: name (str) - the skill's name; days (int, 1..365, default 30).
    Output: SkillAutopsy: counts of tool calls, tool errors, interrupts,
      corrections and tokens (null where the transcripts recorded none), the
      risk categories seen, the ones the installed version's review did not
      disclose, and up to five recent spans with a short redacted excerpt.
      ``state`` is ``not_measured`` when no transcript was ever scanned.
    Example: GET /api/v1/skills/deploy/autopsy?days=30
    """
    return SkillAutopsy(**await asyncio.to_thread(_autopsy_now, request, name[:128], days))


@router.post("/catalog/installed/{install_id}/restore", response_model=InstalledItemView,
             dependencies=[Depends(require_auth)])
async def restore_installed(request: Request, install_id: str,
                            body: InstalledUpdateRequest) -> InstalledItemView:
    """Reinstall the recorded version of one install over its edited or missing copy.

    Raises:
        HTTPException(404): no such install.
        HTTPException(409): ``stale_revision``, ``restore_unavailable`` (the
            index no longer holds this version at the recorded digest),
            ``digest_mismatch``, or ``consent_required`` exactly as an update;
            ``version_revoked`` / ``key_untrusted`` when the publisher revoked the
            recorded version or its signing key; ``restore_missing`` when a
            recorded folder is gone (reinstall instead).
    """
    services = request.app.state.services
    row = await asyncio.to_thread(row_now, request, install_id)
    if row.revision != body.expected_revision:
        raise stale_409(row)
    snapshot = await services.catalog.index_cache.get()
    refuse_empty(snapshot)
    item, untrusted = find_item(snapshot, row.item_id)
    version = None if item is None or untrusted else next(
        (v for v in item.versions if v.v == row.version and v.digest == row.digest), None)
    if version is None:
        raise refuse_409(RESTORE_UNAVAILABLE,
                         f"the index no longer carries {row.item_id!r} {row.version!r} at the recorded digest")
    revoked_keys, revoked_versions = await asyncio.to_thread(
        services.catalog.index_cache.revoked_sets, snapshot.verified)
    if version_subject(item.id, version.v) in revoked_versions:
        raise refuse_409(VERSION_REVOKED, f"{row.item_id!r} {row.version!r} was revoked by the publisher")
    if version.sig.key_id.strip().upper() in revoked_keys:
        raise refuse_409(KEY_UNTRUSTED, f"the key that signed {row.item_id!r} {row.version!r} was revoked")
    if not await asyncio.to_thread(_restorable, request, row):
        raise refuse_409(RESTORE_MISSING, "the installed folder is gone; reinstall it instead of restoring")
    view = await apply_version(request, row, item, version, body, snapshot)
    await asyncio.to_thread(_set_forked, services, install_id, False)
    view.forked = False
    return view


@router.put("/catalog/installed/{install_id}/fork", response_model=InstalledItemView,
            dependencies=[Depends(require_auth)])
async def set_installed_fork(request: Request, install_id: str,
                             body: ForkRequest) -> InstalledItemView:
    """Mark (or unmark) one install keep-as-fork: auto-update then refuses to overwrite it.

    Inputs: install_id (str); body.forked (bool). Output: the row with the mark set.
    Raises: HTTPException(404) when no ledger row carries that id.
    """
    services = request.app.state.services
    row = await asyncio.to_thread(row_now, request, install_id)
    await asyncio.to_thread(_set_forked, services, install_id, body.forked)
    view = installed_view(row, services.catalog.index_cache.snapshot())
    await asyncio.to_thread(annotate_watch, services, [row], [view])
    return view
