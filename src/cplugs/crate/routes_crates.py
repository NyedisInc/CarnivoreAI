
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Path as PathParam, Query, Request
from fastapi.responses import FileResponse

from src.cplugs.crate import download, removal
from src.cplugs.crate import service_crates as svc
from src.cplugs.crate import upload
from src.cplugs.crate.errors import answered
from src.cplugs.crate.models import CopyBody, ExtractBody, IdentityBody, RemoveBody, VerifyBody
from src.cplugs.crate.refs import BUNDLE_ID_PATTERN, CrateRef
from src.cplugs.sdk import CplugContext

_FOLDER = "^(primary|second)$"


def add_to(router: APIRouter, ctx_dep: Any) -> None:

    @router.get("/bundles")
    async def get_bundles(project: Optional[int] = Query(None, ge=1), ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Every recorded bundle, or one project's."""
        return await answered(svc.bundles(ctx, project))

    @router.get("/bundles/{bundle_id}")
    async def get_bundle(bundle_id: str = PathParam(..., pattern=BUNDLE_ID_PATTERN),
                         ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """One bundle and a plain crate's summary."""
        return await answered(svc.bundle(ctx, bundle_id))

    @router.get("/bundles/{bundle_id}/download")
    async def get_bundle_download(bundle_id: str = PathParam(..., pattern=BUNDLE_ID_PATTERN), part: str = Query(download.PART_CRATE),
                                  ctx: CplugContext = ctx_dep) -> FileResponse:
        """A bundle's crate file (or its checksum file), streamed as an attachment."""
        return await answered(download.download(ctx, CrateRef(bundle_id=bundle_id), part))

    @router.post("/bundles/{bundle_id}/contents")
    async def post_bundle_contents(body: Optional[IdentityBody] = None,
                                   bundle_id: str = PathParam(..., pattern=BUNDLE_ID_PATTERN),
                                   ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """A bundle's file records and row counts."""
        return await answered(svc.contents(ctx, CrateRef(bundle_id=bundle_id), body.identity_text() if body else None))

    @router.post("/bundles/{bundle_id}/verify", status_code=202)
    async def post_bundle_verify(body: VerifyBody, bundle_id: str = PathParam(..., pattern=BUNDLE_ID_PATTERN),
                                 ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Verify a bundle's locations as a job."""
        return await answered(svc.start_verify(ctx, CrateRef(bundle_id=bundle_id), body.level, body.location,
                                               body.identity_text()))

    @router.post("/bundles/{bundle_id}/copies", status_code=202)
    async def post_bundle_copy(body: CopyBody, bundle_id: str = PathParam(..., pattern=BUNDLE_ID_PATTERN),
                               ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Copy a bundle to the second folder as a job."""
        return await answered(svc.start_copy(ctx, bundle_id, body.identity_text()))

    @router.post("/bundles/{bundle_id}/extract")
    async def post_bundle_extract(body: ExtractBody, bundle_id: str = PathParam(..., pattern=BUNDLE_ID_PATTERN),
                                  ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Write one conversation of a bundle into a scratch folder."""
        return await answered(svc.extract(ctx, CrateRef(bundle_id=bundle_id), body.conversation_id,
                                          body.identity_text()))

    @router.get("/folders/{folder}/crates")
    async def get_folder_crates(folder: str = PathParam(..., pattern=_FOLDER),
                                ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """The crate files in a crate folder."""
        return await answered(svc.folder_crates(ctx, folder))

    @router.post("/folders/primary/crates/upload", status_code=201)
    async def post_crate_upload(request: Request, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Receive a crate file (the raw body) into the primary crates folder."""
        announced = request.headers.get("content-length", "")
        return await answered(upload.receive(ctx, request.headers.get("x-crate-name", ""), request.stream(),
                                             int(announced) if announced.isdigit() else None,
                                             request.headers.get("x-crate-sha256")))

    @router.post("/crates/remove")
    async def post_crate_remove(body: RemoveBody, ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Move a crate (and its sidecars) to the Trash."""
        return await answered(removal.remove_crate(ctx, body))

    @router.get("/folders/{folder}/crates/{name}/download")
    async def get_folder_download(folder: str = PathParam(..., pattern=_FOLDER), name: str = PathParam(..., max_length=128),
                                  part: str = Query(download.PART_CRATE), ctx: CplugContext = ctx_dep) -> FileResponse:
        """A folder crate (or its checksum file), streamed as an attachment."""
        return await answered(download.download(ctx, CrateRef(folder=folder, name=name), part))

    @router.post("/folders/{folder}/crates/{name}/contents")
    async def post_folder_contents(body: Optional[IdentityBody] = None, folder: str = PathParam(..., pattern=_FOLDER),
                                   name: str = PathParam(..., max_length=128),
                                   ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """A folder crate's file records and row counts."""
        return await answered(svc.contents(ctx, CrateRef(folder=folder, name=name),
                                           body.identity_text() if body else None))

    @router.post("/folders/{folder}/crates/{name}/verify", status_code=202)
    async def post_folder_verify(body: VerifyBody, folder: str = PathParam(..., pattern=_FOLDER),
                                 name: str = PathParam(..., max_length=128),
                                 ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Verify a folder crate as a job."""
        return await answered(svc.start_verify(ctx, CrateRef(folder=folder, name=name), body.level, None,
                                               body.identity_text()))

    @router.post("/folders/{folder}/crates/{name}/extract")
    async def post_folder_extract(body: ExtractBody, folder: str = PathParam(..., pattern=_FOLDER),
                                  name: str = PathParam(..., max_length=128),
                                  ctx: CplugContext = ctx_dep) -> Dict[str, Any]:
        """Write one conversation of a folder crate into a scratch folder."""
        return await answered(svc.extract(ctx, CrateRef(folder=folder, name=name), body.conversation_id,
                                          body.identity_text()))
