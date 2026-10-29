
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional

from src.core.claude_resume_argv import is_claude_command
from src.core.conversation_writers import ProcessTable

FAMILY_CLAUDE: str = "claude"
FAMILY_CODEX: str = "codex"
_LSTART_FORMAT = "%a %b %d %H:%M:%S %Y"


def lstart_to_datetime(lstart: str) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(time.mktime(time.strptime(" ".join(lstart.split()), _LSTART_FORMAT)),
                                      timezone.utc)
    except (ValueError, OverflowError):
        return None


def is_codex_command(command: str) -> bool:
    tokens = command.split()[:2]
    return any(os.path.basename(t) == FAMILY_CODEX for t in tokens)


def find_agent(table: ProcessTable, pane_pid: Optional[int], family: str) -> Optional[int]:
    if pane_pid is None:
        return None
    test = is_claude_command if family == FAMILY_CLAUDE else is_codex_command
    for proc in table.descendants(pane_pid):
        if test(proc.command):
            return proc.pid
    return None
