
from __future__ import annotations

import re
from typing import List, Optional

from src.core.agy.transcripts import read_messages, transcript_path
from src.core.copilot.store import read_prompts as read_copilot_prompts

MAX_PROMPTS = 500
MAX_PROMPT_CHARS = 20000
_REQUEST = re.compile(r"<USER_REQUEST>\n?(.*?)\n?</USER_REQUEST>", re.DOTALL)


def agy_prompt(text: str) -> str:
    found = _REQUEST.search(text)
    return (found.group(1) if found else text).strip()


def read_custom_prompt_texts(conversation_id: Optional[str]) -> List[str]:
    path = transcript_path(conversation_id) if conversation_id else None
    if path is not None:
        texts = [agy_prompt(m["text"]) for m in read_messages(path) if m["role"] == "user"]
    else:
        texts = read_copilot_prompts(conversation_id)
    return [t[:MAX_PROMPT_CHARS] for t in texts if t][-MAX_PROMPTS:]
