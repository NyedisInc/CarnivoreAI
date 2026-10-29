
from __future__ import annotations

from typing import Callable, Iterator, Match, Optional, Pattern


def accepted_matches(
    regex: Pattern[str], text: str, accept: Optional[Callable[[Match[str]], bool]]
) -> Iterator[Match[str]]:
    if accept is None:
        yield from regex.finditer(text)
        return
    pos = 0
    while pos <= len(text):
        match = regex.search(text, pos)
        if match is None:
            return
        if accept(match):
            yield match
            pos = match.end()
        else:
            pos = match.end("name")
