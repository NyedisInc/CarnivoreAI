
from __future__ import annotations

import re
from typing import Iterable, List, Sequence

MAX_BODY = 2000
MAX_SUBJECTS = 5
MAX_PATHS = 5
MAX_SHOWN = 80
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean(text: str, limit: int) -> str:
    return " ".join(_CONTROL.sub(" ", str(text or "")).replace("|", "/").split())[:limit]


def relative_paths(paths: Iterable[str]) -> List[str]:
    return [p for p in paths if isinstance(p, str) and p and not p.startswith(("/", "~")) and ".." not in p.split("/")]


def build(item_title: str, who: str, session_name: str, subjects: Sequence[str], commit_count: int, paths: Sequence[str], file_count: int,
          cost_text: str, summary: str) -> str:
    shown = [clean(s, MAX_SHOWN) for s in subjects[:MAX_SUBJECTS] if clean(s, MAX_SHOWN)]
    safe = [clean(p, MAX_SHOWN) for p in relative_paths(paths)[:MAX_PATHS]]
    parts = [clean(item_title, 120), f"{clean(who, 80) or 'someone'}'s session {clean(session_name, 80)}",
             f"commits: {int(commit_count)}" + (f" ({'; '.join(shown)})" if shown else ""),
             f"files: {int(file_count)}" + (f" ({', '.join(safe)})" if safe else ""),
             f"cost this window: {clean(cost_text, 20) or '-'}"]
    head = " | ".join(parts)
    tail = clean(summary, 300)
    body = f"{head} | {tail}" if tail else head
    return body[:MAX_BODY]
