
from __future__ import annotations

from typing import Any, Dict

from fastapi import Depends, Query

from src.cplugs.crate import constants as K
from src.cplugs.crate import routes_crates, routes_imports, service
from src.cplugs.crate.errors import answered
from src.cplugs.crate.models import ExportBody, FamiliesBody, PlanBody
from src.cplugs.sdk import CplugContext, cplug_context, cplug_router

router = cplug_router("crate")
Ctx = Depends(cplug_context("crate"))


@router.get("/summary")
async def get_summary(ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The folders, the encryption defaults, the running job and the bundle count."""
    return await answered(service.summary(ctx))


@router.post("/backup-families")
async def post_backup_families(body: FamiliesBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The backup ticks an export of this scope offers: the conversations', and one per plugin folder it owns a part of."""
    return await answered(service.backup_families(ctx, body.model_dump()))


@router.post("/plan")
async def post_plan(body: PlanBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """What an export would carry, leave out and refuse."""
    return await answered(service.plan(ctx, body.model_dump()))


@router.post("/exports", status_code=202)
async def post_export(body: ExportBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Start the export the quoted plan describes."""
    fields = body.model_dump()
    fingerprint = fields.pop("fingerprint")
    return await answered(service.start_export(ctx, fields, fingerprint))


@router.get("/jobs")
async def get_jobs(limit: int = Query(K.JOBS_LIMIT_DEFAULT, ge=1, le=K.JOBS_LIMIT_MAX),
                   ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The newest jobs."""
    return await answered(service.jobs(ctx, limit))


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """One job."""
    return await answered(service.job(ctx, job_id))


@router.post("/jobs/{job_id}/cancel")
async def post_cancel(job_id: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Ask the running job to stop."""
    return await answered(service.cancel(ctx, job_id))


routes_crates.add_to(router, Ctx)
routes_imports.add_to(router, Ctx)
