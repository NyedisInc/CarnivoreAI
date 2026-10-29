
from __future__ import annotations

from typing import Optional, Tuple

from src.cplugs.sdk import signed_links

TTL_S = 3600
LABEL = "huddle-artifact-ticket-v1"


def mint(item_id: int, file_id: str, now: Optional[float] = None, ttl_s: int = TTL_S) -> str:
    return signed_links.mint(LABEL, [str(int(item_id)), file_id], ttl_s, now)


def verify(ticket: str, now: Optional[float] = None) -> Optional[Tuple[int, str]]:
    fields = signed_links.verify(LABEL, ticket, 2, now)
    return (int(fields[0]), fields[1]) if fields and fields[0].isdigit() else None


__all__ = ["TTL_S", "mint", "verify"]
