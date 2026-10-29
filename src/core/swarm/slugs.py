
from __future__ import annotations

import re
from typing import Callable

SLUG_RULE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
MAX_SLUG_LENGTH = 48
_FALLBACK = "agent"


def is_valid_slug(slug: str) -> bool:
    return isinstance(slug, str) and SLUG_RULE.match(slug) is not None


def slugify(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    words = re.sub(r"^[^a-z]+", "", words)[:MAX_SLUG_LENGTH].rstrip("-")
    return words or _FALLBACK


def mint_slug(job: str, taken: Callable[[str], bool]) -> str:
    base = slugify(job)
    candidate, n = base, 1
    while taken(candidate):
        n += 1
        suffix = f"-{n}"
        candidate = base[: MAX_SLUG_LENGTH - len(suffix)].rstrip("-") + suffix
    return candidate
