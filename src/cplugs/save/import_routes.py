
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.cplugs.save import import_service as svc
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.save.vault.old_sources import labels, model
from src.cplugs.sdk import vault_sources

_STATUS = {"bad_verdict": 400, "import_busy": 409, "plan_changed": 409, "bad_path": 400, "bad_allow_list": 400, "unknown_point": 400, "no_such_run": 404, "nothing_to_undo": 409}


class FolderRef(BaseModel):
    """A plain folder of transcripts to read: ``path`` and the ``name`` its copies are reported under."""

    path: str
    name: Optional[str] = None


class PointRef(BaseModel):
    """One planned point to file: ``id`` (the unit) and ``point_id``, as ``review/keep-ids.json`` lists them."""

    id: str = Field(min_length=1, max_length=200)
    point_id: str = Field(min_length=1, max_length=64)


class ImportSources(BaseModel):
    """What to take in. Every path is absolute and read only."""

    archives: List[str] = Field(default_factory=list, description="old archive databases (cloude-archive.db)")
    folders: List[FolderRef] = Field(default_factory=list, description="plain folders of transcripts, e.g. the hold folder")
    old_stores: List[str] = Field(default_factory=list, description="folders holding the retired save store (time-machine/)")
    tar_roots: List[str] = Field(default_factory=list, description="folders of cleanup tars (and loose transcripts)")
    recovered_root: Optional[str] = Field(None, description="the recovered-transcripts folder: its transcripts, its table dumps and audit logs")
    plan_applied: Optional[str] = Field(None, description="the 09-30 cleanup's plan-applied.json (junk, review and kept labels)")
    trash_manifests: List[str] = Field(default_factory=list, description="the trash sha256 manifests (trash label)")
    rows_file: Optional[str] = Field(None, description="the final plan json (row of each folder)")
    secret_rows: List[str] = Field(default_factory=list, description="the row ids flagged for pasted secrets")
    reorg_rules: List[str] = Field(default_factory=list, description="the reorg path rule files (rules-*.tsv)")
    newest_only: bool = Field(True, description="read the newest row of each archive path")
    only_points: Optional[List[PointRef]] = Field(None, max_length=5000, description="allow-list: file only these planned points ({id, point_id}); every other copy is skip:not_selected; absent files all; an unknown point is refused (unknown_point)")
    quick: bool = Field(False, description="preview only: trust the archives' and old store's recorded hashes instead of reading every byte")


class PreviewResult(BaseModel):
    """The preview: a fingerprint for apply, whether it was quick, and the counts."""

    fingerprint: str
    quick: bool
    counts: Dict[str, Any]


class ReviewBody(BaseModel):
    """The once-over verdict: ``keep`` or ``junk`` on imported conversations, dated like 20261022."""

    units: List[str] = Field(min_length=1, max_length=500)
    verdict: str
    date: str


class ApplyBody(ImportSources):

    fingerprint: str = Field(min_length=64, max_length=64)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.ImportRefused):
        return HTTPException(status_code=_STATUS.get(exc.code, 400), detail={"code": exc.code, "detail": exc.detail})
    if isinstance(exc, VaultUnavailable):
        return HTTPException(status_code=409, detail={"code": "vault_unavailable", "detail": str(exc)})
    if isinstance(exc, (model.SourceError, labels.LabelError, vault_sources.SourceUnavailable)):
        return HTTPException(status_code=400, detail={"code": "source_unreadable", "detail": str(exc)[:300]})
    return HTTPException(status_code=500, detail={"code": "import_failed", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"})


_EXPECTED = (svc.ImportRefused, VaultUnavailable, model.SourceError, labels.LabelError, vault_sources.SourceUnavailable, OSError)


async def _run(call, *args: Any) -> Any:
    try:
        return await run_in_threadpool(call, *args)
    except _EXPECTED as exc:
        raise _translate(exc) from exc


def add_to(router: APIRouter) -> None:

    @router.post("/imports/preview", response_model=PreviewResult)
    async def preview(body: ImportSources) -> PreviewResult:
        """Count what would be taken in, writing nothing. Output: PreviewResult."""
        return PreviewResult(**await _run(svc.preview_blocking, body.model_dump()))

    @router.post("/imports/apply")
    async def apply(body: ApplyBody) -> Dict[str, Any]:
        """File the previewed plan (add only). Output: the receipt."""
        data = body.model_dump()
        return await _run(svc.apply_blocking, data, data.pop("fingerprint"))

    @router.get("/imports")
    async def imports_list() -> Dict[str, Any]:
        """Every import receipt, newest first. Output: ``{imports}``."""
        return {"imports": await _run(svc.receipts_blocking)}

    @router.get("/imports/{run_id}")
    async def imports_get(run_id: str) -> Dict[str, Any]:
        """One import receipt. Output: the receipt."""
        return await _run(svc.receipts_blocking, run_id)

    @router.post("/imports/review")
    async def imports_review(body: ReviewBody) -> Dict[str, Any]:
        """Add ``reviewed-<date>:<verdict>`` to the tags of imported conversations (``keep`` lifts the deep search hold). Output: ``{updated, refused}``."""
        return await _run(svc.review_blocking, body.units, body.verdict, body.date)

    @router.get("/imports/{run_id}/verify")
    async def imports_verify(run_id: str) -> Dict[str, Any]:
        """Read a run's points back and compare every file to what the run set out to file; reconcile every copy. Output: the report."""
        return await _run(svc.verify_blocking, run_id)

    @router.post("/imports/{run_id}/undo")
    async def imports_undo(run_id: str) -> Dict[str, Any]:
        """Remove exactly what the run filed. Output: ``{run_id, state, undo}``."""
        return await _run(svc.undo_blocking, run_id)
