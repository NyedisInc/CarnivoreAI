
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Pattern, Sequence, Tuple

from src.config.mcp_launch import CLAUDE_DEV_CHANNELS_FLAG, SERVER_NAME
from src.core.approvals.extract import DEV_CHANNELS_ACCEPT, DEV_CHANNELS_TITLE, FAMILY_CLAUDE, KIND_OTHER, ROLE_OPTION

OUR_CHANNEL: str = f"server:{SERVER_NAME}"
OUR_FLAG_TOKEN: str = f"{CLAUDE_DEV_CHANNELS_FLAG}={OUR_CHANNEL}"
CLAUDE_EXECUTABLE: str = "claude"

_CHANNELS_LINE: Pattern[str] = re.compile(r"^\s*Channels:\s*(?P<rest>.*)$")
_ROW_LINE: Pattern[str] = re.compile(r"^\s*(?:[❯›>]\s*)?\d+\.\s+\S")
_FLAG_ANY: Pattern[str] = re.compile(r"(?:^|\s)" + re.escape(CLAUDE_DEV_CHANNELS_FLAG) + r"(?=[=\s]|$)")
_FLAG_OURS: Pattern[str] = re.compile(r"(?:^|\s)" + re.escape(OUR_FLAG_TOKEN) + r"(?=\s|$)")

def is_dev_channels_dialog(dialog: Any) -> bool:
    if dialog is None or dialog.family != FAMILY_CLAUDE or dialog.kind != KIND_OTHER:
        return False
    if dialog.question.strip() != DEV_CHANNELS_TITLE:
        return False
    labels = [r.label for r in dialog.rows if r.role == ROLE_OPTION]
    return len(dialog.rows) == 2 and DEV_CHANNELS_ACCEPT in labels and "Exit" in labels


def listed_channels(dialog: Any) -> Optional[Tuple[str, ...]]:
    lines = (getattr(dialog, "body", "") or "").splitlines()
    at = next((i for i, ln in enumerate(lines) if _CHANNELS_LINE.match(ln)), None)
    if at is None:
        return None
    parts = [_CHANNELS_LINE.match(lines[at]).group("rest")]  # type: ignore[union-attr]
    for line in lines[at + 1:]:
        if _ROW_LINE.match(line):
            break
        parts.append(line)
    tokens = tuple(t for t in re.split(r"[,\s]+", " ".join(parts)) if t)
    return tokens or None


def carnivore_answers(dialog: Any) -> bool:
    return is_dev_channels_dialog(dialog) and listed_channels(dialog) == (OUR_CHANNEL,)


def _descends(pid: int, ancestor: int, parents: Dict[int, int]) -> bool:
    cursor: Optional[int] = pid
    for _ in range(64):
        if cursor is None:
            return False
        if cursor == ancestor:
            return True
        cursor = parents.get(cursor)
    return False


def launched_with_our_flag(pane_pid: Optional[int], rows: Optional[Sequence[Any]]) -> Optional[bool]:
    if pane_pid is None or rows is None:
        return None
    parents = {int(r.pid): int(r.ppid) for r in rows}
    agents = [r for r in rows
              if (r.command or "").split(" ", 1)[0].rsplit("/", 1)[-1] == CLAUDE_EXECUTABLE
              and _descends(int(r.pid), pane_pid, parents)]
    flagged = [r for r in agents if _FLAG_ANY.search(r.command)]
    if not flagged:
        return False
    return all(len(_FLAG_ANY.findall(r.command)) == 1 and _FLAG_OURS.search(r.command) for r in flagged)
