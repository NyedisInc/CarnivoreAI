
from __future__ import annotations

from typing import Tuple

MARK_COMPACT = "compact"
MARK_BOOKMARK = "bookmark"
MARK_RESTART = "restart"
MARK_RESTORE = "restore"
MARK_KINDS: Tuple[str, ...] = (MARK_COMPACT, MARK_BOOKMARK, MARK_RESTART, MARK_RESTORE)

MILESTONE_SLEEP = "sleep"
MILESTONE_RESTART = "restart"
WAKE_KINDS: Tuple[str, ...] = ("restart", "clear", "fork", "rewind", "resume", "switch", "kill", "remove")

SNIPPET_CHARS = 160
DEFAULT_PEEK_TURNS = 4
MAX_PEEK_TURNS = 20
