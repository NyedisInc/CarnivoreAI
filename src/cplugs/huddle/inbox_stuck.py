
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, Optional

import structlog

from src.cplugs.huddle import original_ask, rules, title as titles
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.roles import ask

logger = structlog.get_logger()

QUOTE_CHARS = 200


def _context(entry: Dict[str, Any], wait_s: float) -> str:
    flat = " / ".join(part.strip() for part in entry["text"].strip().splitlines() if part.strip())
    quoted = flat if len(flat) <= QUOTE_CHARS else flat[:QUOTE_CHARS - 1].rstrip() + "..."
    minutes = max(1, round(wait_s / 60))
    return f'nobody filed this in {minutes} minute{"" if minutes == 1 else "s"}: "{quoted}"'


def raise_question(inboxes: InboxStore, entry: Dict[str, Any], wait_s: float) -> Optional[int]:
    previous = inboxes.mark_stuck(entry["id"])
    if previous is None:
        return None
    store = inboxes._store
    try:
        first = entry["text"].strip().splitlines()[0]
        carrier = store.add(entry["list"], entry["text"], actor=rules.CLAUDE, created_key=rules.CARNIVORE_KEY, state=rules.TODO,
                            title=first[:titles.MAX_TITLE])
        with closing(store._connect(True)) as conn, conn:
            original_ask.copy_link(conn, carrier["id"], entry["id"])
        ask.carnivore_ask(store, carrier["id"], category=ask.INBOX_STUCK, context=_context(entry, wait_s),
                          options=ask.INBOX_OPTIONS, labels=ask.INBOX_LABELS)
    except (rules.TaskManagerError, OSError) as exc:
        inboxes.retire_questions(entry["id"])
        inboxes.rearm(entry["id"], entry["created_at"], previous)
        logger.error("task_manager_inbox_stuck_failed", entry=entry["id"], error_type=type(exc).__name__, error=str(exc)[:200])
        raise
    logger.info("task_manager_inbox_stuck_asked", entry=entry["id"], list=entry["list"], carrier=carrier["id"])
    return carrier["id"]
