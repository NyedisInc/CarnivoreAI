
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictStr

from src.api.auth import require_auth
from src.core.dev_tools import git_guard
from src.cplugs.host import identity, sideload, sideload_git, sideload_routes
from src.cplugs.host.owner_switch import _runtime as _sidecar_runtime

logger = structlog.get_logger()

router = APIRouter(prefix="/cplug-owner", tags=["cplugs"], dependencies=[Depends(require_auth)])
_one_at_a_time = asyncio.Lock()


class GitBody(BaseModel):
    """The repository to sideload: its URL and, optionally, a branch, tag or commit, a subfolder and the install name."""

    model_config = ConfigDict(extra="forbid")
    url: StrictStr
    ref: Optional[StrictStr] = None
    subdir: Optional[StrictStr] = None
    name: Optional[StrictStr] = None


def _check_name(given: Optional[str]) -> None:
    if given is not None and not identity.INSTALL_NAME.match(given):
        raise sideload.SideloadRefused("name_invalid", f"an install name must match {identity.INSTALL_NAME.pattern}", 409)


def _fetch_blocking(state_dir: Path, url: str, ref: Optional[str], parts: tuple, given: Optional[str]) -> Dict[str, Any]:
    checkout = sideload_git.checkout_of(state_dir, given) if given else sideload_git.incoming(state_dir)
    fresh = not (checkout / ".git").is_dir()
    try:
        commit = sideload_git.fetch(checkout, url, ref)
        source = sideload_git.source_in(checkout, parts)
        name = sideload_routes.name_of(source, given)
        if not given:
            fresh = not sideload_git.checkout_of(state_dir, name).exists()
            checkout = sideload_git.adopt(state_dir, checkout, name)
            source = sideload_git.source_in(checkout, parts)
    except BaseException:
        if fresh or not given:
            shutil.rmtree(checkout, ignore_errors=True)
        raise
    return {"checkout": checkout, "fresh": fresh, "source": source, "name": name, "commit": commit}


@router.post("/sideload/git")
async def post_sideload_git(body: GitBody, request: Request) -> Dict[str, Any]:
    """Sideload (or re-sync) a plugin from a git repository. Output: the folder sync's answer plus ``git``."""
    live = _sidecar_runtime(request)
    state_dir = live.state_dir
    sideload_routes.require_on(state_dir)
    try:
        url = sideload_git.check_url(body.url)
        ref = sideload_git.check_ref(body.ref)
        parts = sideload_git.check_subdir(body.subdir)
        _check_name(body.name)
    except sideload.SideloadRefused as exc:
        raise sideload_routes._refuse(exc) from exc
    if not await asyncio.to_thread(git_guard.git_available):
        raise HTTPException(status_code=503, detail={"code": "git_unavailable", "detail": "git is not installed on this computer"})
    async with _one_at_a_time:
        try:
            got = await asyncio.to_thread(_fetch_blocking, state_dir, url, ref, parts, body.name)
        except sideload.SideloadRefused as exc:
            raise sideload_routes._refuse(exc) from exc
        except OSError as exc:
            logger.warning("cplug_sideload_git_checkout_failed", url=sideload_git.redacted(url), error_type=type(exc).__name__)
            raise HTTPException(status_code=500, detail={"code": "sideload_failed", "detail": "the checkout could not be written"}) from exc
        try:
            answer = await sideload_routes.sync_folder(live, got["source"], got["name"])
        except BaseException:
            if got["fresh"]:
                await asyncio.to_thread(shutil.rmtree, got["checkout"], True)
            raise
        try:
            entry = await asyncio.to_thread(sideload_git.record, state_dir, got["name"], url, ref, parts, got["commit"])
        except sideload.SideloadRefused as exc:
            raise sideload_routes._refuse(exc) from exc
    logger.info("cplug_sideload_git_synced", name=got["name"], url=sideload_git.redacted(url), commit=got["commit"],
                unchanged=answer["unchanged"])
    return {**answer, "git": entry}
