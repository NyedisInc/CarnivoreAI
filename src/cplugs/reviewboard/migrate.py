
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog
from pydantic import ValidationError

from src.cplugs.reviewboard import artifact_source, opener, pages, publish, service, wire
from src.cplugs.reviewboard.errors import BoardError
from src.cplugs.reviewboard.requests import CreateBody, ReviseBody
from src.cplugs.sdk import CplugContext, browser_pages

logger = structlog.get_logger()

MARKER_FILE = ".huddle-artifacts-copied.json"
ROW_KEY_PREFIX = "huddle_artifact:"


def _marker(root: Path) -> Path:
    return root / MARKER_FILE


def _written(root: Path, boards: int, revisions: int, rows: int) -> None:
    text = json.dumps({"version": 1, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "boards": boards, "revisions": revisions,
                       "rows_moved": rows}, indent=2)
    _marker(root).write_text(text + "\n", encoding="utf-8")


def _epoch(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)


def _groups(posted: List[Dict[str, Any]]) -> Dict[Tuple[int, str], List[Dict[str, Any]]]:
    out: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    for entry in posted:
        out.setdefault((entry["item_id"], pages.title_key(entry["title"])), []).append(entry)
    return out


async def _copy_group(ctx: CplugContext, root: Path, source: artifact_source.ArtifactSource, versions: List[Dict[str, Any]],
                      slugs: Dict[Tuple[int, str], str], key: Tuple[int, str]) -> int:
    slug = await asyncio.to_thread(pages.existing_board, root, key[0], versions[0]["title"])
    have = 0
    if slug is not None:
        have = len(((await asyncio.to_thread(service.board, root, slug)).get("sidecar") or {}).get("revisions", []))
    written = 0
    for entry in versions[have:]:
        html = await source.page(entry["item_id"], entry["file_id"])
        if html is None:
            logger.info("reviewboard_copy_page_gone", item=entry["item_id"], file=entry["file_id"])
            continue
        summary = (entry["description"] or entry["title"]).strip()
        at = _epoch(entry["created_at"])
        try:
            if slug is None:
                taken = await asyncio.to_thread(pages.taken_today, root)
                body = CreateBody.model_validate(pages.create_args(entry["item_id"], entry["title"], summary, html, taken))
                slug = (await publish.create_board(ctx, body, None, False, post_card=False, at=at))["slug"]
            else:
                await publish.add_revision(ctx, slug, ReviseBody.model_validate(pages.revise_args(summary, html)), None, False, post_card=False, at=at)
        except (BoardError, ValidationError) as exc:
            logger.warning("reviewboard_copy_page_refused", item=entry["item_id"], file=entry["file_id"], reason=str(exc)[:200])
            continue
        written += 1
    if slug is not None:
        slugs[key] = slug
    return written


def _move_rows(posted: List[Dict[str, Any]], slugs: Dict[Tuple[int, str], str]) -> int:
    by_file = {(e["item_id"], e["file_id"]): slugs.get((e["item_id"], pages.title_key(e["title"]))) for e in posted}
    moved = 0
    for row in browser_pages.open_artifact_rows():
        ref = row.ref or {}
        slug = by_file.get((ref.get("item"), ref.get("artifact")))
        if slug and browser_pages.replace_row(row.id, opener.page_path(slug), row.title):
            moved += 1
    return moved


async def run(ctx: CplugContext) -> Optional[Dict[str, int]]:
    source = artifact_source.get()
    if source is None:
        return None
    try:
        root = wire.explicit_root(ctx)
        if await asyncio.to_thread(_marker(root).exists):
            return None
        posted = await source.posted()
        slugs: Dict[Tuple[int, str], str] = {}
        revisions = 0
        groups = _groups(posted)
        for key, versions in groups.items():
            revisions += await _copy_group(ctx, root, source, versions, slugs, key)
        rows = await asyncio.to_thread(_move_rows, posted, slugs)
        await asyncio.to_thread(_written, root, len(slugs), revisions, rows)
    except (BoardError, OSError) as exc:
        logger.warning("reviewboard_copy_failed", error=type(exc).__name__, reason=str(exc)[:200])
        return None
    logger.info("reviewboard_copy_done", boards=len(slugs), revisions=revisions, rows_moved=rows)
    return {"boards": len(slugs), "revisions": revisions, "rows_moved": rows}
