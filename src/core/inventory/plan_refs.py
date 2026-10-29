
from __future__ import annotations

import re
from typing import List, Sequence

_SLUG = rb"([A-Za-z0-9][A-Za-z0-9._-]{0,159})"


def plan_slugs(line: bytes, homes: Sequence[str]) -> List[str]:
    text = line.replace(b"\\/", b"/")
    found: List[str] = []
    for home in homes:
        pattern = re.escape(home.rstrip("/").encode("utf-8")) + rb"/plans/" + _SLUG + rb"\.md(?![A-Za-z0-9._-])"
        for match in re.finditer(pattern, text):
            slug = match.group(1).decode("ascii")
            if slug not in found and not slug.endswith("."):
                found.append(slug)
    return found
