
from __future__ import annotations

import asyncio
import os
import re
from typing import List, Optional

import structlog

from src.core.pack.jobs.types import JobError
from src.core.pack.session_place import create

logger = structlog.get_logger()


def _named(brief: str, name: str) -> bool:
    return re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w/-])", brief) is not None


def clash(brief: str, dirty: List[str]) -> Optional[str]:
    text = brief.replace("\\", "/")
    for rel in dirty:
        if _named(text, rel) or _named(text, os.path.basename(rel)):
            return rel
    for rel in dirty:
        folder = os.path.dirname(rel)
        while folder:
            if _named(text, folder) or _named(text, folder + "/"):
                return folder + "/"
            folder = os.path.dirname(folder)
    return None


def _reason(folder: str, brief: str) -> Optional[str]:
    try:
        hit = clash(brief, dirty_of(folder))
    except (JobError, OSError) as exc:
        logger.info("same_file_guard_unread", error_type=type(exc).__name__)
        return None
    return f"{hit} is being edited on this computer" if hit else None


def dirty_of(folder: str) -> List[str]:
    return create.dirty_files(folder)


async def reason_for(folder: str, brief: str) -> Optional[str]:
    if not brief.strip():
        return None
    return await asyncio.to_thread(_reason, folder, brief)
