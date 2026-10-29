
from __future__ import annotations

from functools import lru_cache
from typing import Dict, Mapping

from src.core.notifications import catalog_lines

WHICH_SESSION = "which_session"
HELD = "held"
NOT_RUNNING = "not_running"
WAKE_REFUSED = "wake_refused"
NOT_IMESSAGE = "not_imessage"
RATE_LIMITED = "rate_limited"
NOBODY_LISTENS = "nobody_listens"
GAP = "gap"
TEST = "test"
ALL = (WHICH_SESSION, HELD, NOT_RUNNING, WAKE_REFUSED, NOT_IMESSAGE, RATE_LIMITED, NOBODY_LISTENS, GAP, TEST)

NOTE_EDITED = "messaging.note.edited"
NOTE_UNSENT = "messaging.note.unsent"

UNSENT_SNIPPET_CHARS = 80


@lru_cache(maxsize=1)
def copy() -> Dict[str, str]:
    return catalog_lines.read_prefixed(("messaging.",))


def fill(template: str, params: Mapping[str, object]) -> str:
    out = template
    for key, value in params.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def notice_text(name: str, **params: object) -> str:
    return fill(copy()[f"messaging.notice.{name}"], params)


def edited_note(new_text: str) -> str:
    return fill(copy()[NOTE_EDITED], {"text": new_text})


def unsent_note(old_text: str) -> str:
    snippet = " ".join(old_text.split())
    if len(snippet) > UNSENT_SNIPPET_CHARS:
        snippet = snippet[:UNSENT_SNIPPET_CHARS] + "..."
    return fill(copy()[NOTE_UNSENT], {"text": snippet})
