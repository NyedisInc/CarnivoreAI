
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from src.cplugs.reviewboard import attachment_guard, attachment_secrets, ports, revisions, scratch, service, store, wire
from src.cplugs.reviewboard.errors import (BadRequest, BoardError, TaskManagerRefused, NoTaskManager, ReadOnlyBoard, ScratchBoard, StoreFailed,
                                           TaskNotFound, TooLarge, Unlinked)
from src.cplugs.reviewboard.scratch import Upload
from src.cplugs.reviewboard.scratch_files import EXT_ID as SCRATCH_EXT_ID
from src.cplugs.reviewboard.schema import Sidecar
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import AgentCaller, CplugContext
from src.cplugs.sdk.computer import local_computer
from src.cplugs.sdk.uploads import UploadRefused, check_bytes

logger = structlog.get_logger()

EXT_ID = "attachments"
EXT_VERSION = 1
MAX_FILES = scratch.MAX_FILES
MAX_TOTAL_BYTES = scratch.MAX_TOTAL_BYTES
MAX_BODY_BYTES = (MAX_TOTAL_BYTES * 4 + 2) // 3 + 1024 * 1024
MAX_ATTACHMENTS = 500
MAX_NOTE = 2000
MAX_THREAD_TEXT = 4000
FILE_ID = re.compile(r"^[0-9a-f]{8}$")
ATTACHER = "attached_by"
ENTRY_FIELDS = ("file_id", "item_id", "message_id", "name", "mime", "bytes", "sha256", "added_at", "revision")
REMOVED_AT = "removed_at"
_MAX_REVIEW_SUMMARY = 300
_MAX_REVIEW_DESCRIPTION = 4000


def decode_inline(value: Any) -> List[Upload]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BadRequest("files must be a list of {name, content_base64}")
    if len(value) > MAX_FILES:
        raise TooLarge(f"an attach carries at most {MAX_FILES} files, not {len(value)}")
    for i, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != {"name", "content_base64"} or not isinstance(entry["content_base64"], str):
            raise BadRequest(f"files[{i}] must be {{name, content_base64}}")
    encoded = sum(len(e["content_base64"]) for e in value)
    if encoded * 3 // 4 > MAX_TOTAL_BYTES + 3 * len(value):
        raise TooLarge(f"an attach carries at most {MAX_TOTAL_BYTES // (1024 * 1024)} MB of files")
    out = []
    for i, entry in enumerate(value):
        try:
            data = base64.b64decode(entry["content_base64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise BadRequest(f"files[{i}].content_base64 is not base64") from exc
        out.append(Upload(entry["name"] if isinstance(entry["name"], str) else "", data))
    return out


def check_uploads(uploads: Sequence[Upload]) -> List[Tuple[str, bytes]]:
    if not uploads:
        raise BadRequest("an attach needs at least one file")
    if len(uploads) > MAX_FILES:
        raise TooLarge(f"an attach carries at most {MAX_FILES} files, not {len(uploads)}")
    total = sum(len(u.data) for u in uploads)
    if total > MAX_TOTAL_BYTES:
        raise TooLarge(f"an attach carries at most {MAX_TOTAL_BYTES // (1024 * 1024)} MB of files, not {total} bytes")
    out: List[Tuple[str, bytes]] = []
    for upload in uploads:
        if not upload.name.strip():
            raise BadRequest("each file needs a name")
        try:
            data, name = check_bytes(upload.data, upload.name)
        except UploadRefused as exc:
            raise BadRequest(f"{upload.name[:80]}: {exc}") from exc
        attachment_guard.check_type(name, data)
        out.append((name, data))
    return out


def is_entry(entry: Any) -> bool:
    if not isinstance(entry, dict) or not set(ENTRY_FIELDS) <= entry.keys():
        return False
    ints = ("item_id", "message_id", "bytes")
    return all(isinstance(entry[k], int) and not isinstance(entry[k], bool) for k in ints) and all(
        isinstance(entry[k], str) for k in ENTRY_FIELDS if k not in ints) and bool(FILE_ID.match(entry["file_id"]))


def entries_of(sidecar: Dict[str, Any]) -> List[Dict[str, Any]]:
    block = (sidecar.get("ext") or {}).get(EXT_ID) if isinstance(sidecar, dict) else None
    files = block.get("files") if isinstance(block, dict) else None
    if not isinstance(files, list):
        return []
    out = []
    for e in files:
        if is_entry(e):
            row = {k: e[k] for k in ENTRY_FIELDS}
            if isinstance(e.get(ATTACHER), str) and e[ATTACHER]:
                row[ATTACHER] = e[ATTACHER]
            if is_removed(e):
                row[REMOVED_AT] = e[REMOVED_AT] if isinstance(e[REMOVED_AT], str) else ""
            out.append(row)
    return out


def is_removed(entry: Dict[str, Any]) -> bool:
    return REMOVED_AT in entry


def _with_urls(entries: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        port: Optional[ports.BoardPort] = ports.get()
    except NoTaskManager:
        port = None
    return [{**{k: v for k, v in e.items() if k != ATTACHER}, "url": port.file_url(e["item_id"], e["file_id"]) if port is not None else None}
            for e in entries]



async def listing(ctx: CplugContext, slug: str) -> Dict[str, Any]:
    root = wire.board_root(ctx)
    found = await asyncio.to_thread(service.board, root, slug)
    sidecar = found.get("sidecar") if found.get("status") == "ok" else None
    entries = entries_of(sidecar or {})
    return {"slug": slug, "attachments": _with_urls([e for e in entries if not is_removed(e)]),
            "removed": [{k: v for k, v in e.items() if k != ATTACHER} for e in entries if is_removed(e)]}


def _linked_task(found: Dict[str, Any], slug: str) -> int:
    sidecar = found.get("sidecar")
    if found.get("status") != "ok" or not isinstance(sidecar, dict):
        raise ReadOnlyBoard(f"{slug} cannot be written here, so nothing is attached to it")
    if SCRATCH_EXT_ID in (sidecar.get("ext") or {}):
        raise ScratchBoard(f"{slug} is a scratch board: its files come with its posts (task_manager_scratch_post)")
    task = sidecar.get("task")
    if not isinstance(task, dict) or not task.get("item_id"):
        raise Unlinked(f"{slug} has no task to attach files to; link one first")
    here = local_computer()
    if task.get("computer") and here and task["computer"] != here:
        raise Unlinked(f"{slug}'s task is on {task['computer']}, so its files cannot be stored here")
    return int(task["item_id"])


def _review(title: str, names: str, note: str) -> Dict[str, str]:
    line = " ".join(f"{title}: attached {names}".split())
    return {"summary": line[:_MAX_REVIEW_SUMMARY], "description": (note or line)[:_MAX_REVIEW_DESCRIPTION], "where": f"review board: {title}"}


def thread_text(title: str, names: str, note: str) -> str:
    line = f"attached to board {title}: {names}"
    text = f"{line}\n\n{note}" if note else line
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise BadRequest("the note and the board title may not contain control characters")
    if len(text) > MAX_THREAD_TEXT:
        raise BadRequest(f"the thread line is over the task manager's {MAX_THREAD_TEXT} character limit; shorten the note or attach fewer files")
    return text


def _index(root: Path, state_folder: Path, slug: str, new: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    written: List[Dict[str, Any]] = []

    def build(current: Optional[Sidecar]) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
        assert current is not None
        doc = service.sidecar_json(current)
        if SCRATCH_EXT_ID in doc["ext"]:
            raise ScratchBoard(f"{slug} is a scratch board: its files come with its posts")
        block = doc["ext"].setdefault(EXT_ID, {"v": EXT_VERSION, "files": []})
        files = block.setdefault("files", [])
        if not isinstance(files, list):
            raise BadRequest(f"{slug}'s attachment index is not a list; fix the sidecar by hand first")
        if len(files) + len(new) > MAX_ATTACHMENTS:
            raise TooLarge(f"a board holds at most {MAX_ATTACHMENTS} attachments")
        revision = current.revisions[-1].id if current.revisions else "r1"
        written[:] = [{**e, "revision": revision} for e in new]
        files.extend(written)
        return doc, {}

    _text, tag = store.append(root, state_folder, slug, None, build)
    return tag, [{k: e[k] for k in ENTRY_FIELDS} for e in written]


async def attach(ctx: CplugContext, slug: str, uploads: Sequence[Upload], *, note: Optional[str] = None, request_review: bool = True,
                 caller: Optional[AgentCaller] = None, cross_project: bool = False) -> Dict[str, Any]:
    checked = check_uploads(uploads)
    await asyncio.to_thread(attachment_secrets.refuse_secrets, checked, slug=slug)
    note = (note or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(note) > MAX_NOTE:
        raise BadRequest(f"note is at most {MAX_NOTE} characters")
    root = wire.board_root(ctx)
    found = await asyncio.to_thread(service.board, root, slug)
    item_id = _linked_task(found, slug)
    port = ports.get()
    if await port.item_info(item_id) is None:
        raise TaskNotFound(f"there is no task manager item {item_id} on this computer")
    await port.check_caller(caller, item_id, cross_project)
    if len(entries_of(found["sidecar"])) + len(checked) > MAX_ATTACHMENTS:
        raise TooLarge(f"a board holds at most {MAX_ATTACHMENTS} attachments")
    title = str(found["sidecar"]["board"]["title"])
    names = ", ".join(name for name, _data in checked)
    text = thread_text(title, names, note)
    posted = await port.attach_files(caller, item_id, uploads=checked, text=text, request_review=request_review,
                                     review=_review(title, names, note), cross_project=cross_project)
    if posted.get("message_id") is None:
        _refusal(posted, item_id)
    now = revisions.stamp(revisions.utcnow())
    attacher = await port.caller_key(caller)
    new = [{**({ATTACHER: attacher} if attacher else {}), "file_id": f["id"], "item_id": item_id, "message_id": int(posted["message_id"]), "name": f["name"], "mime": f["mime"],
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "added_at": now}
           for f, (_name, data) in zip(posted["files"], checked)]
    answer = {"slug": slug, "message_id": int(posted["message_id"]), "review": posted.get("review")}
    try:
        tag, written = await asyncio.to_thread(_index, root, ctx.storage.path, slug, new)
    except (BoardError, OSError) as exc:
        logger.error("reviewboard_attach_index_failed", slug=slug, item=item_id, message=posted["message_id"], files=len(new),
                     error=type(exc).__name__)
        ctx.notify(TOPIC)
        return {**answer, "attachments": _with_urls(new), "etag": None, "indexed": False,
                "warning": f"attached to the task (message {posted['message_id']}), but the board's index was not updated: {exc}"[:500]}
    ctx.notify(TOPIC)
    logger.info("reviewboard_attached", slug=slug, item=item_id, files=len(written), bytes=sum(e["bytes"] for e in written))
    return {**answer, "attachments": _with_urls(written), "etag": tag, "indexed": True}


def _refusal(posted: Dict[str, Any], item_id: int) -> None:
    code = posted.get("code")
    if code == "store_failed":
        raise StoreFailed(f"{posted.get('refused')}, so nothing was attached")
    if code:
        raise TaskManagerRefused(f"the task refused the attach ({code}): {posted.get('refused')}", extra={"task_code": code})
    raise TaskNotFound(f"task manager item {item_id} is gone, so nothing was attached")


__all__ = ["EXT_ID", "MAX_BODY_BYTES", "MAX_FILES", "MAX_TOTAL_BYTES", "REMOVED_AT", "attach", "check_uploads", "decode_inline", "entries_of", "is_entry", "is_removed", "listing"]
