"""The viewer ticket: how an ``<iframe src>`` proves it may read one artifact (``artifacts.py``).

An iframe (and a pop-out window) cannot send the app's bearer token, so the authenticated route ``POST .../artifacts/{id}/ticket`` mints a
SIGNED, SHORT-LIVED ticket naming exactly one item and one file (``sdk/signed_links.py``), and the viewer route accepts only that.
"""

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
