
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Path

from src.cplugs.crate import import_undo, imports
from src.cplugs.crate.errors import answered
from src.cplugs.crate.models import ImportBody, ImportPlanBody
from src.cplugs.sdk import CplugContext


def has_start_route(router: APIRouter) -> bool:
    return any(getattr(r, "path", "").endswith("/imports") and "POST" in (getattr(r, "methods", None) or ()) for r in router.routes)


def add_to(router: APIRouter, ctx_dep: Any) -> None:

    @router.post("/imports/plan")
    async def post_import_plan(body: ImportPlanBody, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """What restoring a crate here would do. Writes nothing."""
        fields = body.model_dump(exclude={"identity"}, exclude_none=True)
        fields["identity"] = body.identity_text()
        out = await answered(imports.plan(ctx, fields, allow_made_here=True))
        out["start_available"] = has_start_route(router)
        return out

    @router.post("/imports", status_code=202)
    async def post_import(body: ImportBody, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Restore the crate the quoted plan describes, as a job."""
        fields = body.model_dump(exclude={"identity"}, exclude_none=True)
        fields["identity"] = body.identity_text()
        return await answered(imports.start(ctx, fields, allow_made_here=True))

    @router.get("/imports")
    async def get_imports(ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """The receipts of finished imports, newest first."""
        return await answered(imports.list_imports(ctx))

    @router.get("/imports/{import_id}/undo")
    async def get_import_undo(import_id: str = Path(..., max_length=64), ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """What undoing a finished import would do, and what blocks it. Writes nothing."""
        return await answered(import_undo.preview(ctx, import_id))

    @router.post("/imports/{import_id}/undo")
    async def post_import_undo(import_id: str = Path(..., max_length=64), ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Take a finished import back (the module docstring says exactly what that means)."""
        return await answered(import_undo.undo(ctx, import_id))

    @router.get("/imports/{import_id}")
    async def get_import(import_id: str = Path(..., max_length=64), ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """One finished import's receipt."""
        return await answered(imports.get_import(ctx, import_id))
