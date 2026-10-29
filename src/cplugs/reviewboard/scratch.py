
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import structlog
from pydantic import ValidationError

from src.cplugs.reviewboard import drafts, layout, ports, publish, service, store, wire
from src.cplugs.reviewboard.errors import BadRequest, NotScratch, TooLarge
from src.cplugs.reviewboard.requests import CreateBody, ReviseBody
from src.cplugs.reviewboard.schema import MAX_VIEW_BYTES, Sidecar
from src.cplugs.reviewboard.scratch_files import EXT_ID, EXT_VERSION, GITIGNORE, GITIGNORE_TEXT, NAME, is_scratch, rel_path
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import AgentCaller, CplugContext
from src.cplugs.sdk.uploads import UploadRefused, check_bytes, is_image_name, safe_name

logger = structlog.get_logger()

MAX_FILES = 10
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_BODY_BYTES = (MAX_TOTAL_BYTES * 4 + 2) // 3 + 2 * MAX_VIEW_BYTES + 1024 * 1024
DEFAULT_VIEWPORT = 1024
DEFAULT_SUMMARY = "scratch post"
TASK_PREFIX = "scratch: "
_CREATING = asyncio.Lock()


@dataclass(frozen=True)
class Upload:

    name: str
    data: bytes


@dataclass(frozen=True)
class ScratchPost:

    name: str
    html: str
    title: Optional[str] = None
    summary: Optional[str] = None
    viewport: Optional[int] = None
    files: Sequence[Upload] = ()


@dataclass(frozen=True)
class _File:

    name: str
    data: bytes
    image: bool


def check_name(declared: Any) -> str:
    if not isinstance(declared, str) or not declared:
        raise BadRequest("each file needs a name")
    if "/" in declared or "\\" in declared or ".." in declared:
        raise BadRequest(f"file name {declared[:80]!r} may not hold a path separator or ..: name the file, not a path")
    if not NAME.fullmatch(declared) or safe_name(declared) != declared:
        raise BadRequest(f"file name {declared[:80]!r} must be letters, digits, '.', '_' or '-' (at most 128, not starting with . or -)")
    return declared


def check_files(files: Sequence[Upload]) -> List[_File]:
    if len(files) > MAX_FILES:
        raise TooLarge(f"a scratch post carries at most {MAX_FILES} files, not {len(files)}")
    total = sum(len(f.data) for f in files)
    if total > MAX_TOTAL_BYTES:
        raise TooLarge(f"a scratch post carries at most {MAX_TOTAL_BYTES // (1024 * 1024)} MB of files, not {total} bytes")
    out: List[_File] = []
    seen = set()
    for upload in files:
        name = check_name(upload.name)
        if name in seen:
            raise BadRequest(f"two files are named {name}")
        seen.add(name)
        try:
            data, _safe = check_bytes(upload.data, name)
        except UploadRefused as exc:
            raise BadRequest(f"{name}: {exc}") from exc
        out.append(_File(name, data, is_image_name(name)))
    return out


def _decorator(files: Sequence[_File], label: Optional[str]) -> publish.Decorate:
    def decorate(current: Optional[Sidecar], doc: Dict[str, Any], out: Dict[str, bytes]) -> None:
        if current is not None and not is_scratch(current):
            raise NotScratch(f"{current.board.slug} is a review board, not a scratch board")
        n = len(doc["revisions"])
        rev = doc["revisions"][-1]
        manifest = []
        for f in files:
            out[rel_path(n, f.name)] = f.data
            manifest.append({"name": f.name, "file": rel_path(n, f.name), "sha256": hashlib.sha256(f.data).hexdigest(), "bytes": len(f.data),
                             "image": f.image})
        rev["ext"] = {EXT_ID: {"v": EXT_VERSION, "files": manifest}}
        if label:
            rev["by"]["label"] = label
        if current is None:
            doc["ext"][EXT_ID] = {"v": EXT_VERSION}
            out[GITIGNORE] = GITIGNORE_TEXT

    return decorate


def find_board(root: Path, name: str) -> Optional[Dict[str, Any]]:
    rows = service.boards(root)["boards"]
    return next((r for r in rows if r.get("scratch") and r["status"] == "ok" and r["slug"][9:] == name), None)


def _refuse_taken(root: Path, name: str) -> None:
    slug = f"{datetime.now().astimezone():%Y%m%d}-{name}"
    if layout.board_dir(root, slug) is not None:
        raise NotScratch(f"{slug} is already a board that is not a valid scratch board; pick another name")


def _who(caller: Optional[AgentCaller]) -> Dict[str, Any]:
    if caller is None:
        return {"by": "owner"}
    if caller.external:
        return {"by": "token", "token": caller.token_name}
    return {"by": "session", "session": caller.current_session_id}


def _valid(model: Any, data: Dict[str, Any]) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        shown = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors()[:5])
        raise BadRequest(shown) from exc


async def _scratch_task(caller: Optional[AgentCaller], title: str, name: str) -> int:
    filed = await ports.get().add_task(caller, title=f"{TASK_PREFIX}{title}", text=(
        f"scratch board {name}: every post to it lands here as a revision (a page and its files). It stays until it is cleared on the board."))
    if not filed.get("filed"):
        raise BadRequest(f"the Scratch task could not be filed: {filed.get('reason')}")
    return int(filed["task"]["item_id"])


async def post(ctx: CplugContext, request: ScratchPost, caller: Optional[AgentCaller] = None, cross_project: bool = False) -> Dict[str, Any]:
    files = check_files(request.files)
    root = wire.board_root(ctx)
    label = f"token {caller.token_name}"[:120] if caller is not None and caller.external else None
    decorate = _decorator(files, label)
    count = f"{len(files)} file{'' if len(files) == 1 else 's'}"
    summary = (request.summary or "").strip() or f"{DEFAULT_SUMMARY}, {count}"
    async with _CREATING:
        row = await asyncio.to_thread(find_board, root, request.name)
        if row is not None:
            body = _valid(ReviseBody, {"summary": summary, "html": request.html, "viewport": request.viewport, "request_review": False})
            answer = await publish.add_revision(ctx, row["slug"], body, caller, cross_project, decorate)
            task = (row.get("task") or {}).get("item_id")
        else:
            title = (request.title or "").strip() or request.name
            fields = {"slug_name": request.name, "title": title, "kind": "other", "summary": summary, "html": request.html,
                      "viewport": request.viewport or DEFAULT_VIEWPORT, "request_review": False}
            _valid(CreateBody, {**fields, "task": {"item_id": 1}})
            await asyncio.to_thread(_refuse_taken, root, request.name)
            task = await _scratch_task(caller, title, request.name)
            answer = await publish.create_board(ctx, _valid(CreateBody, {**fields, "task": {"item_id": task}}), caller, cross_project, decorate)
    n = int(answer["revision"][1:])
    logger.info("reviewboard_scratch_post", slug=answer["slug"], revision=answer["revision"], created=row is None, **_who(caller),
                page_bytes=len(request.html.encode("utf-8")), files=len(files), file_bytes=sum(len(f.data) for f in files))
    return {**answer, "created": row is None, "task": task,
            "files": [{"name": f.name, "bytes": len(f.data), "image": f.image, "file": rel_path(n, f.name)} for f in files]}


async def clear(ctx: CplugContext, slug: str) -> Dict[str, Any]:
    root = wire.board_root(ctx)
    removed = await asyncio.to_thread(store.remove, root, ctx.storage.path, slug)
    ctx.notify(TOPIC)
    if await asyncio.to_thread(drafts.clear, ctx.storage.path, slug):
        ctx.notify(drafts.TOPIC)
    return removed


__all__ = ["MAX_BODY_BYTES", "MAX_FILES", "MAX_TOTAL_BYTES", "ScratchPost", "Upload", "check_files", "check_name", "clear", "post"]
