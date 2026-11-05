
from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api.checkpoint_revert_routes import RevertKept, _blocked_by, _kept, _refused, require_owner
from src.api.error_response import api_error
from src.api.session_bookmark_routes import _bookmark, rewind_point
from src.core.bookmarks import rows
from src.core.checkpoints import bookmark_rewind
from src.core.checkpoints import revert as revert_mod
from src.core.checkpoints.store import get_store, state_root
from src.models.bookmarks import RewindPointRequest, RewindResponse

router = APIRouter(tags=["session-bookmarks"])


class RewindFilesRequest(BaseModel):
    """A rewind of a bookmark's files, alone or after its conversation."""

    mode: Literal["files", "both"] = Field(description="files: the files only; both: the conversation, then the files")
    confirm: bool = Field(False, description="the ticked arm box")


class RewindFilesResponse(BaseModel):
    """What moved. ``files_restored`` false with ``files_error`` set: the conversation moved and the files did not."""

    mode: str
    conversation: Optional[RewindResponse] = None
    checkpoint_id: int
    files_restored: bool
    files_error: Optional[str] = Field(None, description='"conversation rewound, files not restored"; the snapshot is kept')
    why: Optional[str] = Field(None, description="what the file step hit")
    safety_id: Optional[int] = Field(None, description="the snapshot taken first; reverting to it undoes the file step")
    changed: List[str] = Field(default_factory=list)
    created: List[str] = Field(default_factory=list)
    deleted: List[str] = Field(default_factory=list)
    kept: List[RevertKept] = Field(default_factory=list)


@router.post("/bookmarks/{bookmark_id}/rewind/files", response_model=RewindFilesResponse,
             dependencies=[Depends(require_owner)])
async def rewind_bookmark_files(request: Request, bookmark_id: int, body: RewindFilesRequest) -> RewindFilesResponse:
    """Put the files back to the bookmark's turn, alone (``files``) or after the conversation (``both``).

    400 without ``confirm``; 409 ``bookmark_files_unavailable`` (mid-turn, or no snapshot), ``revert_blocked`` or a
    snapshot that cannot be read, all before anything moves; a conversation refusal is the rewind's own error.
    """
    if not body.confirm:
        raise api_error(400, "revert_confirm_required")
    mark = await _bookmark(bookmark_id)
    row = await run_in_threadpool(rows.read_row, mark.session_uuid)
    store = get_store()
    cp = await run_in_threadpool(bookmark_rewind.turn_snapshot, store, mark.session_uuid, mark.entry_uuid)
    if cp is None:
        reason = await run_in_threadpool(bookmark_rewind.files_unavailable, store, mark.as_dict(), row.working_dir)
        raise api_error(409, "bookmark_files_unavailable", extra={"reason": reason})
    try:
        plan = await run_in_threadpool(revert_mod.preview, store, cp, state_root())
    except revert_mod.RevertRefused as exc:
        raise _refused(exc) from exc
    include_own = body.mode == bookmark_rewind.MODE_FILES
    blocked = await _blocked_by(request, row, cp.work_tree, include_own=include_own)
    if blocked:
        raise api_error(409, "revert_blocked", extra={"blocking": blocked})

    async def conversation() -> dict:
        done = await rewind_point(request, mark.session_uuid, RewindPointRequest(
            entry_uuid=mark.entry_uuid, conversation=mark.claude_session_uuid, confirm=body.confirm))
        return done.model_dump()

    async def files() -> revert_mod.RevertResult:
        again = await _blocked_by(request, row, cp.work_tree, include_own=include_own)
        if again:
            raise revert_mod.RevertRefused(409, "revert_blocked", "; ".join(again))
        return await run_in_threadpool(revert_mod.revert, store, cp, plan.fingerprint, state_root())

    try:
        out = await bookmark_rewind.run(body.mode, conversation=conversation, files=files)
    except revert_mod.RevertRefused as exc:
        raise _refused(exc) from exc
    done = out.files
    return RewindFilesResponse(
        mode=body.mode, conversation=RewindResponse(**out.conversation) if out.conversation else None,
        checkpoint_id=cp.id, files_restored=done is not None, files_error=out.files_error, why=out.why,
        safety_id=done.safety.id if done else None, changed=done.plan.change if done else [],
        created=done.plan.create if done else [], deleted=done.plan.delete if done else [],
        kept=_kept(done.kept) if done else [])
