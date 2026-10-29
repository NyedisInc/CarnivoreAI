
from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import actor_log, board, files, held, kinds, lifecycle, own_list, reply, service, task_files, send_queue, title
from src.cplugs.huddle.store_files import BYTES_DELETED, BYTES_FAILED, Located
from src.cplugs.huddle.sending import CHANNEL_META_KIND
from src.cplugs.huddle.rules import ALL_LIST, CLAUDE, JOE, OPEN, REVIEW, TODO, WAITING, TaskManagerError, TaskManagerNotFound
from src.cplugs.sdk import AgentCaller, CapabilityMissing, CplugContext, CplugSchemaError, ports, task_folders
from src.cplugs.sdk.file_deletion import FileDeletion
from src.cplugs.sdk.routing import router_prefix

logger = structlog.get_logger()

NAME = "huddle.board"
MAX_TASK_TITLE = title.MAX_TITLE
MOVABLE_STATES = frozenset({OPEN, WAITING})
_ISSUE = re.compile(r"^https://github\.com/([^/]+/[^/]+)/issues/([0-9]+)$")
FILE_URL = "/api/v1" + router_prefix("huddle") + "/items/{item_id}/files/{file_id}"
FILE_BAD_ID = "not a stored file id"
FILE_MISSING = "the file's bytes are already gone"
FILE_MISMATCH = "the stored file is not the one the board recorded, so it is kept"
FILE_UNREADABLE = "the stored file could not be checked, so it is kept"
FILE_SHARED = "another message on the task still carries this file"
TASK_DELETED = "the task was deleted"
TASK_MISSING = "the task does not exist"
STORE_UNWRITABLE = "the huddle could not be written"
UNLINK_FAILED = "the file could not be removed from disk"
_Write = Callable[[CplugContext, Optional[AgentCaller], dict], Awaitable[Dict[str, Any]]]


def _issue_ref(url: Optional[str]) -> Optional[str]:
    match = _ISSUE.match(url or "")
    return f"{match.group(1)}#{match.group(2)}" if match else None


def _info(item: Dict[str, Any], project: Optional[str]) -> Dict[str, Any]:
    return {"item_id": item["id"], "list": item["list"], "project": project, "title": title.display(item), "state": item["state"],
            "status": item["status"], "github_issue": _issue_ref(item.get("github_issue"))}


def _project_names(ctx: CplugContext) -> Dict[str, str]:
    try:
        return service.project_names(ctx)
    except CapabilityMissing:
        return {}


class BoardPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    async def item_info(self, item_id: int) -> Optional[Dict[str, Any]]:
        def read() -> Dict[str, Any]:
            item = service.store(self._ctx).item(item_id)
            return {**_info(item, task_files.project_name(self._ctx, item["list"])), "store_id": task_files.own_store_id(self._ctx)}

        try:
            return await asyncio.to_thread(read)
        except TaskManagerNotFound:
            return None

    async def items_info(self, item_ids: Sequence[int]) -> Optional[Dict[int, Dict[str, Any]]]:
        wanted = sorted({int(i) for i in item_ids})

        def read() -> Dict[int, Dict[str, Any]]:
            found = service.store(self._ctx).items_by_id(wanted)
            names = _project_names(self._ctx) if any(task_folders.is_project_key(i["list"]) for i in found.values()) else {}
            return {item_id: _info(item, names.get(item["list"])) for item_id, item in found.items()}

        if not wanted:
            return {}
        try:
            return await asyncio.to_thread(read)
        except (sqlite3.Error, OSError, CplugSchemaError) as exc:
            logger.warning("reviewboard_items_unread", items=len(wanted), error=type(exc).__name__)
            return None

    async def check_caller(self, caller: Optional[AgentCaller], item_id: int, cross_project: bool) -> None:
        if caller is None:
            return
        found = await own_list.targets(self._ctx, {"item": item_id})
        await own_list.judge(self._ctx, caller, found, cross_project)

    async def add_task(self, caller: Optional[AgentCaller], *, title: str, text: str) -> Dict[str, Any]:
        list_key = (await own_list.own_project(self._ctx, caller) if caller is not None else None) or ALL_LIST
        key = (await actor_log.caller_key(self._ctx, caller) if caller is not None else None) or ""
        actor = CLAUDE if caller is not None else JOE
        try:
            item = await asyncio.to_thread(lambda: service.store(self._ctx).add(list_key, text, actor=actor, title=title[:MAX_TASK_TITLE],
                                                                                created_key=key, state=TODO))
        except TaskManagerError as exc:
            logger.info("reviewboard_task_refused", list=list_key, code=exc.code)
            return {"filed": False, "reason": str(exc)[:300] or exc.code}
        except sqlite3.Error as exc:
            logger.warning("reviewboard_task_failed", list=list_key, error=type(exc).__name__)
            return {"filed": False, "reason": "the huddle could not be written"}
        info = await self.item_info(int(item["id"]))
        return {"filed": True, "task": info} if info is not None else {"filed": False, "reason": f"item {item['id']} vanished once filed"}

    async def post_card(self, caller: Optional[AgentCaller], item_id: int, *, text: str, card: Dict[str, Any], request_review: bool,
                        review: Dict[str, str], cross_project: bool) -> Dict[str, Any]:
        async def board_card(ctx: CplugContext, who: Optional[AgentCaller], args: dict) -> Dict[str, Any]:
            store = service.store(ctx)
            key = (await actor_log.caller_key(ctx, who) if who is not None else None) or ""
            try:
                posted = await asyncio.to_thread(lambda: store.post(item_id, text, actor=CLAUDE, kind=kinds.INFO, author_key=key,
                                                                     parts=board.parts_of(card), notify=True))
            except TaskManagerNotFound:
                return {"message_id": None, "review": {"requested": request_review, "moved": False, "reason": "the item is gone"}}
            outcome = {"requested": request_review, "moved": False, "reason": None}
            if request_review:
                outcome.update(await asyncio.to_thread(self._move_to_review, item_id, posted["item"], review))
            return {"message_id": posted["message"]["id"], "review": outcome}

        return await self._guarded(board_card, caller, item_id, cross_project)

    async def attach_files(self, caller: Optional[AgentCaller], item_id: int, *, uploads: Sequence[Tuple[str, bytes]], text: str,
                           request_review: bool, review: Dict[str, str], cross_project: bool) -> Dict[str, Any]:
        async def board_attach(ctx: CplugContext, who: Optional[AgentCaller], args: dict) -> Dict[str, Any]:
            key = (await actor_log.caller_key(ctx, who) if who is not None else None) or ""
            nothing = {"message_id": None, "files": [], "review": {"requested": request_review, "moved": False, "reason": "nothing was attached"}}
            try:
                stored, posted = await asyncio.to_thread(self._store_and_post, item_id, uploads, text, key)
            except TaskManagerNotFound:
                return {**nothing, "review": {**nothing["review"], "reason": "the item is gone"}}
            except TaskManagerError as exc:
                logger.info("reviewboard_attach_refused", item=item_id, code=exc.code)
                return {**nothing, "refused": str(exc)[:300] or exc.code, "code": exc.code}
            except OSError as exc:
                logger.warning("reviewboard_attach_store_failed", item=item_id, error=type(exc).__name__)
                return {**nothing, "refused": f"a file could not be stored ({type(exc).__name__})", "code": "store_failed"}
            outcome = {"requested": request_review, "moved": False, "reason": None}
            if request_review:
                outcome.update(await asyncio.to_thread(self._move_to_review, item_id, posted["item"], review))
            return {"message_id": posted["message"]["id"], "files": stored, "review": outcome}

        return await self._guarded(board_attach, caller, item_id, cross_project)

    async def caller_key(self, caller: Optional[AgentCaller]) -> Optional[str]:
        return await actor_log.caller_key(self._ctx, caller) if caller is not None else None

    async def delete_file(self, item_id: int, message_id: int, file_id: str, *, name: str, size: int, sha256: str) -> FileDeletion:
        return await asyncio.to_thread(self._delete_file, item_id, message_id, file_id, name, size, sha256)

    def _located(self, item_id: int, file_id: str, name: str, size: int, sha256: str) -> Located:
        try:
            path = files.locate(self._ctx.storage, item_id, file_id, task_files.search_dirs(item_id))
        except TaskManagerNotFound:
            return Located(leftovers=tuple(files.leftovers(self._ctx.storage, item_id, file_id, task_files.search_dirs(item_id))))
        try:
            wrong = files.mismatch(path, file_id, name, size, sha256)
        except OSError as exc:
            logger.warning("reviewboard_file_check_failed", item=item_id, file=file_id, error=type(exc).__name__)
            return Located(path, FILE_UNREADABLE)
        return Located(path, FILE_MISMATCH if wrong else None)

    def _delete_file(self, item_id: int, message_id: int, file_id: str, name: str, size: int, sha256: str) -> FileDeletion:
        refused: FileDeletion = {"deleted": False, "shared": False, "redacted": False, "failed": False, "reason": None}
        if not files.ID_PATTERN.match(file_id or ""):
            return {**refused, "reason": FILE_BAD_ID}
        try:
            outcome = service.store(self._ctx).forget_file(item_id, message_id, file_id, lambda: self._located(item_id, file_id, name, size, sha256))
        except TaskManagerNotFound:
            return {**refused, "reason": TASK_DELETED if self._is_deleted(item_id) else TASK_MISSING}
        except (sqlite3.Error, OSError) as exc:
            logger.warning("reviewboard_file_forget_failed", item=item_id, file=file_id, error=type(exc).__name__)
            return {**refused, "failed": True, "reason": STORE_UNWRITABLE}
        state: FileDeletion = {**refused, "shared": outcome["shared"], "redacted": outcome["redacted"]}
        if outcome["shared"]:
            return {**state, "reason": FILE_SHARED}
        if outcome["located"].kept is not None:
            return {**state, "reason": outcome["located"].kept}
        if outcome["bytes"] == BYTES_FAILED:
            return {**state, "failed": True, "reason": UNLINK_FAILED}
        if outcome["bytes"] != BYTES_DELETED:
            return {**state, "reason": FILE_MISSING}
        return state | {"deleted": True}

    def _is_deleted(self, item_id: int) -> bool:
        try:
            service.store(self._ctx).deleted_item(item_id)
        except TaskManagerNotFound:
            return False
        return True

    def file_url(self, item_id: int, file_id: str) -> str:
        if not files.ID_PATTERN.match(file_id or ""):
            raise ValueError("a stored file's id is 8 hex characters")
        return FILE_URL.format(item_id=int(item_id), file_id=file_id)

    async def _guarded(self, write: _Write, caller: Optional[AgentCaller], item_id: int, cross_project: bool) -> Dict[str, Any]:
        if caller is None:
            return await write(self._ctx, None, {})
        return await own_list.guard(write)(self._ctx, caller, {"item": item_id, own_list.FIELD: cross_project})

    def _store_and_post(self, item_id: int, uploads: Sequence[Tuple[str, bytes]], text: str,
                        key: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        store = service.store(self._ctx)
        store.item(item_id)
        target = task_files.folder_for(self._ctx, item_id, task_files.PASTES)
        folders = [target] if target is not None else []
        saved: List[Dict[str, Any]] = []
        try:
            for name, data in uploads:
                saved.append(files.save(self._ctx.storage, item_id, name, data, folder=target))
            parts = files.parts_of([files.describe(self._ctx.storage, item_id, s["id"], folders) for s in saved])
            posted = store.post(item_id, text, actor=CLAUDE, kind=kinds.INFO, author_key=key, parts=parts, notify=True)
        except (TaskManagerError, OSError):
            self._remove_saved(item_id, [s["id"] for s in saved], folders)
            raise
        logger.info("reviewboard_files_attached", item=item_id, files=len(saved), bytes=sum(s["size"] for s in saved))
        return saved, posted

    def _remove_saved(self, item_id: int, file_ids: Sequence[str], folders: Sequence[Path]) -> None:
        for file_id in file_ids:
            try:
                files.locate(self._ctx.storage, item_id, file_id, folders).unlink()
            except (TaskManagerNotFound, OSError) as exc:
                logger.warning("reviewboard_attach_cleanup_failed", item=item_id, file=file_id, error=type(exc).__name__)

    async def post_reply(self, item_id: int, text: str, ref: Dict[str, str]) -> Dict[str, Any]:
        try:
            posted = await reply.post_reply(self._ctx, item_id, text, parts=board.round_parts_of(ref))
        except TaskManagerNotFound:
            return {"posted": False, "reason": f"item {item_id} no longer exists"}
        except TaskManagerError as exc:
            logger.info("reviewboard_reply_refused", item=item_id, code=exc.code)
            return {"posted": False, "reason": str(exc)[:300] or exc.code}
        except (sqlite3.Error, OSError) as exc:
            logger.warning("reviewboard_reply_failed", item=item_id, error=type(exc).__name__)
            return {"posted": False, "reason": "the huddle could not be written"}
        tell = await send_queue.queue_owner_write(self._ctx, posted["item"])
        return {"posted": True, "message_id": posted["message"]["id"], "state": posted["item"].get("state"), "tell": tell}

    async def tell_session(self, session_id: str, text: str) -> Dict[str, Any]:
        try:
            result = await self._ctx.sessions.deliver(session_id, text, {CHANNEL_META_KIND: "reviewboard"})
        except HTTPException as exc:
            logger.info("reviewboard_live_tell_refused", session=session_id, code=held.refusal_code(exc))
            return {"told": False, "reason": held.refusal_reason(exc)[:300]}
        return {"told": True, "via": result.delivered_via}

    def _move_to_review(self, item_id: int, item: Dict[str, Any], review: Dict[str, str]) -> Dict[str, Any]:
        if item["state"] == REVIEW:
            return {"moved": False, "reason": "already in review"}
        if item["state"] not in MOVABLE_STATES:
            return {"moved": False, "reason": f"the item is {item['status']}, so it stays where it is"}
        try:
            service.store(self._ctx).update(item_id, actor=CLAUDE, state=REVIEW, review_fields={
                "review_summary": review["summary"], "review_description": review["description"], "review_where": review["where"],
                "review_action": "answer"})
        except TaskManagerError as exc:
            logger.info("reviewboard_review_not_requested", item=item_id, code=exc.code)
            return {"moved": False, "reason": str(exc)}
        except sqlite3.Error as exc:
            logger.warning("reviewboard_review_failed", item=item_id, error=type(exc).__name__)
            return {"moved": False, "reason": "the huddle could not write the state"}
        return {"moved": True, "reason": None}


def register(ctx: CplugContext) -> None:
    ports.register(NAME, BoardPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)
