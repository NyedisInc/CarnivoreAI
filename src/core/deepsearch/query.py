
from __future__ import annotations

import re
from typing import List, Optional

SEARCH_QUERY_MAX_CHARS: int = 200
SEARCH_TOKENS_MAX: int = 12

_WORD = re.compile(r"\w+", re.UNICODE)


def tokens_of(query: str) -> List[str]:
    return _WORD.findall(query[:SEARCH_QUERY_MAX_CHARS])[:SEARCH_TOKENS_MAX]


def match_expression(query: str) -> Optional[str]:
    tokens = tokens_of(query)
    return " ".join(f'"{t}"*' for t in tokens) if tokens else None
