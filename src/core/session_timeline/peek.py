
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from src.core.bookmarks import locate, preview
from src.core.bookmarks.errors import EntryNotFound, NotClaudeSession
from src.core.bookmarks import rows
from src.core.session_timeline import constants as C
from src.core.session_timeline import gather


def peek(session_key: str, conversation: str, entry_uuid: str, turns: Optional[int] = None,
         db: Optional[Path] = None) -> Dict[str, Any]:
    row, held = gather.conversations_of(session_key, db)
    if rows.family_of(row.agent_type) != "claude":
        raise NotClaudeSession("only Claude Code transcripts can be peeked")
    if conversation not in held:
        raise EntryNotFound("that conversation does not belong to this session")
    used = max(1, min(C.MAX_PEEK_TURNS, int(turns))) if turns is not None else C.DEFAULT_PEEK_TURNS
    path = locate.find_transcript(conversation, row.working_dir)
    return {"conversation": conversation, "entry_uuid": entry_uuid, "turns": used,
            "parts": preview.preview_parts(path, entry_uuid, used)}
