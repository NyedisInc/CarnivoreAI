
from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, Optional

import structlog

from src.plugins.reviewboard.public import links
from src.plugins.sdk import CplugContext
from src.plugins.reviewboard.public.port import PublicBoardMissing, RevisionTexts, port
from src.plugins.sdk.file_secrets import Deadline, ScanTimeout, credential_counts

logger = structlog.get_logger()


class MintRefused(Exception):

    def __init__(self, status: int, code: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.code, self.extra = status, code, extra


def scan(revision: RevisionTexts) -> Dict[str, int]:
    return scan_texts(revision.texts)


def scan_texts(texts: Iterable[str]) -> Dict[str, int]:
    deadline, found = Deadline(), {}
    for text in texts:
        for detector, count in credential_counts(text, deadline).items():
            found[detector] = found.get(detector, 0) + count
    return found


async def mint_link(ctx: CplugContext, board: str, ttl: str, mode: str, revision: Optional[str] = None, *, access: str = "answer",
                    theme: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    boards = port()
    if boards is None:
        raise MintRefused(409, "publicboard_no_reviewboard", "the review board plugin is off, so there is nothing to share")
    try:
        texts = await asyncio.to_thread(boards.revision_texts, board, revision)
    except PublicBoardMissing as exc:
        raise MintRefused(404, "publicboard_not_found", str(exc)) from exc
    try:
        found = await asyncio.to_thread(scan, texts)
    except ScanTimeout as exc:
        logger.warning("publicboard_mint_unscannable", board=board, revision=texts.revision)
        raise MintRefused(422, "publicboard_unscannable", "the board could not be scanned for credentials in time, so it was not shared") from exc
    if found:
        logger.warning("publicboard_mint_refused_secret", board=board, revision=texts.revision, detectors=sorted(found))
        raise MintRefused(422, "publicboard_has_secret", "the board holds what looks like a credential, so it was not shared", detectors=found)
    return await asyncio.to_thread(lambda: links.mint(ctx.storage, board, texts.revision, ttl, mode, links.content_hash(texts.texts),
                                                      access=access, theme=theme))
