
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import structlog

from src.core.attention.transcript_records import (
    is_interrupt,
    is_local_command,
    is_real_user_prompt,
    record_text,
)
from src.core.claude_title_sync import read_tail_records
from src.core.session_transcript_presence import CONVERSATION_PRESENT, conversation_presence

logger = structlog.get_logger()

TAIL_BYTES: int = 8 * 1024 * 1024
MAX_PROMPTS: int = 500
MAX_PROMPT_CHARS: int = 20000


def prompts_from_records(records) -> List[str]:
    out: List[str] = []
    for record in records:
        if not isinstance(record, dict) or not is_real_user_prompt(record):
            continue
        if is_interrupt(record) or is_local_command(record):
            continue
        text = record_text(record).strip()
        if text:
            out.append(text[:MAX_PROMPT_CHARS])
    return out


def read_prompt_texts(
    claude_session_uuid: Optional[str],
    working_dir: Optional[str],
    *,
    corpus_root: Optional[Path] = None,
) -> List[str]:
    presence = conversation_presence(
        claude_session_uuid, working_dir=working_dir, corpus_root=corpus_root)
    if presence.outcome != CONVERSATION_PRESENT or presence.path is None:
        return []
    tail = read_tail_records(str(presence.path), tail_bytes=TAIL_BYTES)
    if not tail.readable:
        logger.info("prompt_texts_unreadable", detail=tail.detail)
        return []
    return prompts_from_records(tail.records)[-MAX_PROMPTS:]
