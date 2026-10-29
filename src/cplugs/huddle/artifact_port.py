
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Dict, List

import structlog

from src.cplugs.huddle import artifacts, files, task_files
from src.cplugs.huddle.rules import TaskManagerNotFound
from src.cplugs.sdk import CplugContext, ports

logger = structlog.get_logger()

NAME = "huddle.artifacts"


class ArtifactPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    def _posted(self) -> List[Dict[str, Any]]:
        with closing(self._ctx.storage.connect(False)) as conn:
            try:
                rows = conn.execute(f"SELECT id, item_id, created_at, parts FROM work_messages WHERE {files.PARTS_SQL} ORDER BY id").fetchall()
            except sqlite3.OperationalError:
                return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            meta = artifacts.meta_of(row["parts"])
            if meta:
                out.append({"item_id": int(row["item_id"]), "message_id": int(row["id"]), "file_id": meta["id"], "title": meta["title"],
                            "description": meta["description"], "size": meta["size"], "created_at": float(row["created_at"])})
        return out

    async def posted(self) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._posted)

    async def page(self, item_id: int, file_id: str) -> str | None:
        def read() -> str | None:
            try:
                path = files.locate(self._ctx.storage, item_id, file_id, task_files.search_dirs(item_id))
                return path.read_text(encoding="utf-8")
            except TaskManagerNotFound:
                return None
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("task_manager_artifact_unreadable", item=item_id, file=file_id, error=type(exc).__name__)
                return None

        return await asyncio.to_thread(read)


def register(ctx: CplugContext) -> None:
    ports.register(NAME, ArtifactPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)
