
from __future__ import annotations

from typing import Optional, Tuple

from src.cplugs.sdk import signed_links

TTL_S = 3600
LABEL = "reviewboard-view-v1"


def mint(slug: str, revision: str, view: str, now: Optional[float] = None, ttl_s: int = TTL_S) -> str:
    return signed_links.mint(LABEL, [slug, revision, view], ttl_s, now)


def verify(ticket: str, now: Optional[float] = None) -> Optional[Tuple[str, str, str]]:
    fields = signed_links.verify(LABEL, ticket, 3, now)
    return (fields[0], fields[1], fields[2]) if fields else None
