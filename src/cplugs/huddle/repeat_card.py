
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

from src.cplugs.huddle import rules

COUNTED_PREFIXES = ("wake_refused:",)
_COUNT_LINE = re.compile(r"\n\nrefused (\d+) times, last at ([^\n]+)\Z")


def is_counted(swarm_ref: str) -> bool:
    return swarm_ref.startswith(COUNTED_PREFIXES)


def find_open(items: Iterable[Dict[str, Any]], swarm_ref: str, title: str) -> Optional[Dict[str, Any]]:
    return next((i for i in items if i.get("swarm_ref") == swarm_ref and (i.get("title") or "") == (title or "")
                 and i.get("state") not in rules.APPROVED_STATES), None)


def next_text(old_text: str, new_text: str, now: Optional[datetime] = None) -> Tuple[str, int]:
    found = _COUNT_LINE.search(old_text)
    count = (int(found.group(1)) if found else 1) + 1
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    return f"{new_text}\n\nrefused {count} times, last at {stamp}", count
