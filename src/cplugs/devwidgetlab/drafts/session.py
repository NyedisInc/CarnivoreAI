
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import structlog
from fastapi import HTTPException

from src.cplugs.devwidgetlab.drafts import brief, store
from src.cplugs.devwidgetlab.errors import SessionUnavailable

logger = structlog.get_logger()

OPENING_PROMPT = "Read BRIEF.md in this folder, then build the widget draft it describes. Work only inside this folder and do not ship anything."


async def hand_to_claude(ctx: Any, storage_path: Path, slug: str) -> Dict[str, Any]:
    repo = store.require_checkout(storage_path)
    folder = store.existing_dir(storage_path, slug)
    brief.retarget(folder / store.BRIEF_FILE, repo)
    record = store.read_record(folder)
    label = f"widget draft: {record['title']}"[:80]
    try:
        session_id = await ctx.sessions.start_in_folder(str(folder), label, OPENING_PROMPT)
    except AttributeError as exc:
        raise SessionUnavailable(str(exc)) from exc
    except (LookupError, HTTPException) as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("widget_lab_hand_to_claude_refused", slug=slug, error_type=type(exc).__name__)
        raise SessionUnavailable(str(detail)) from exc
    store.set_fields(folder, session=session_id, state="working")
    logger.info("widget_lab_draft_handed_to_claude", slug=slug, session_id=session_id)
    return store.summary(folder)
