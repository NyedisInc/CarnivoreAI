from __future__ import annotations

import re
from typing import List, Sequence

QUOTED_ESCAPE = re.compile(r"\\(.|$)", re.DOTALL)


def join_pane_continuations(rows: Sequence[str]) -> List[str]:
    joined: List[str] = []
    for row in rows:
        if "|" in QUOTED_ESCAPE.sub("", row):
            joined.append(row)
        elif joined:
            joined[-1] += "\n" + row
        else:
            joined.append(row)
    return joined


def unquote_pane_path(quoted: str) -> str:
    return QUOTED_ESCAPE.sub(lambda m: m.group(1) or "\n", quoted)
