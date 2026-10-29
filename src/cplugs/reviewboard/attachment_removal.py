
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import structlog

from src.cplugs.reviewboard import attachments, ports, revisions, service, store, wire
from src.cplugs.reviewboard.errors import AttachmentNotFound, BadRequest, BytesNotRemoved, NotAttacher, ReadOnlyBoard
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import AgentCaller, CplugContext

logger = structlog.get_logger()


def _live_entry(sidecar: Dict[str, Any], file_id: str) -> Dict[str, Any]:
    for entry in attachments.entries_of(sidecar):
        if entry["file_id"] == file_id and not attachments.is_removed(entry):
            return entry
    raise AttachmentNotFound(f"this board has no attachment {file_id[:40]}; it may already be removed")


def _tombstone(root: Path, state_folder: Path, slug: str, file_id: str, when: str) -> Tuple[str, Dict[str, Any]]:
    marked: Dict[str, Any] = {}

    def build(current: Any) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
        doc = service.sidecar_json(current)
        files = (doc["ext"].get(attachments.EXT_ID) or {}).get("files")
        if not isinstance(files, list):
            raise BadRequest(f"{slug}'s attachment index is not a list; fix the sidecar by hand first")
        for entry in files:
            if attachments.is_entry(entry) and entry["file_id"] == file_id and not attachments.is_removed(entry):
                entry[attachments.REMOVED_AT] = when
                marked.update({k: entry[k] for k in (*attachments.ENTRY_FIELDS, attachments.REMOVED_AT)})
                return doc, {}
        raise AttachmentNotFound(f"this board has no attachment {file_id[:40]}; it may already be removed")

    _text, tag = store.append(root, state_folder, slug, None, build)
    return tag, marked


async def _require_attacher(caller: AgentCaller, entry: Dict[str, Any]) -> None:
    key = await ports.get().caller_key(caller)
    if not key or entry.get(attachments.ATTACHER) != key:
        raise NotAttacher(f"only the owner or the agent that attached {entry['name'][:60]} may remove it, because removing it deletes the file")


async def _delete_bytes(entry: Dict[str, Any]) -> ports.FileDeletion:
    gone = await ports.get().delete_file(entry["item_id"], entry["message_id"], entry["file_id"], name=entry["name"], size=entry["bytes"],
                                         sha256=entry["sha256"])
    if gone["failed"]:
        raise BytesNotRemoved(f"{entry['name'][:60]} was not removed ({gone['reason']}); nothing is recorded, so try again")
    return gone


async def remove(ctx: CplugContext, slug: str, file_id: str, *, caller: Optional[AgentCaller] = None, cross_project: bool = False) -> Dict[str, Any]:
    if not attachments.FILE_ID.fullmatch(file_id):
        raise BadRequest(f"file_id must be 8 lowercase hex characters, from the board's attachments, not {file_id[:40]!r}")
    root = wire.board_root(ctx)
    found = await asyncio.to_thread(service.board, root, slug)
    sidecar = found.get("sidecar")
    if found.get("status") != "ok" or not isinstance(sidecar, dict):
        raise ReadOnlyBoard(f"{slug} cannot be written here, so nothing is removed from it")
    entry = _live_entry(sidecar, file_id)
    if caller is not None:
        await _require_attacher(caller, entry)
        await ports.get().check_caller(caller, entry["item_id"], cross_project)
    gone = await _delete_bytes(entry)
    when = revisions.stamp(revisions.utcnow())
    tag, tombstone = await asyncio.to_thread(_tombstone, root, ctx.storage.path, slug, file_id, when)
    ctx.notify(TOPIC)
    logger.info("reviewboard_attachment_removed", slug=slug, item=tombstone["item_id"], file_id=file_id, bytes_deleted=gone["deleted"], shared=gone["shared"])
    return {"slug": slug, "file_id": file_id, "removed_at": when, "etag": tag, "attachment": tombstone, "bytes": gone}
