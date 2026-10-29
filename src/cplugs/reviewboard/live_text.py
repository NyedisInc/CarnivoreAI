
from __future__ import annotations

import json
from typing import List

from src.cplugs.reviewboard import round_text
from src.cplugs.reviewboard.schema import LiveDraft, LiveSend

LIMIT = round_text.LIMIT


def read_line(slug: str) -> str:
    return "read it: task_manager_board_get " + json.dumps({"board": slug}) + " (live.sends)"


def summary(title: str, slug: str, send: LiveSend, draft: LiveDraft) -> str:
    context = ", ".join(x for x in (send.context.theme, f"{send.context.width}px" if send.context.width else None) if x)
    head = f"live send {send.n} on the draft ({title})" + (f", {context}" if context else "")
    lines: List[str] = [head, *round_text.answer_lines(draft, send)]
    tail = "\n" + read_line(slug)
    body = "\n".join(lines)
    room = LIMIT - len(tail)
    return (body if len(body) <= room else body[: room - len(round_text.CUT_MARK)].rstrip() + round_text.CUT_MARK) + tail
