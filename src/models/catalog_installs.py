"""What the install-count proxy answers: the hosted summary, relayed.

EVERY FIELD IS OPTIONAL AND NOTHING HAS A FALSY DEFAULT, the same rule
:mod:`src.models.catalog_ratings` opens with and for the same reason. The
hosted api answers ``count: 0`` with an empty ``by_version`` for an item
nobody has installed, and that is a MEASURED ZERO. An item whose counts
could not be read has no count at all. If this model defaulted ``count``
to 0, those two would arrive at the screen identical, and a reader would
be told "nobody has installed this" about an outage.

NOTHING HERE NAMES A PERSON, AND NOTHING UPSTREAM COULD. The row the
hosted summary is built from holds totals only. The idempotency records
that carry a GitHub account id live in a different table that no endpoint
reads, so there is no field this model could have grown that would carry
an identity.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ItemInstallsResponse(BaseModel):
    """`GET /catalog/items/{item_id}/installs`, relayed field for field.

    Fields:
        item_id: the id the hosted api echoed back.
        count: how many installs have been reported. ZERO IS REAL and
            null means this server could not determine it.
        by_version: version string to how many reported that version. An
            EMPTY MAP IS REAL and means nobody has reported any version;
            null means the hosted answer carried no ``by_version`` key at
            all. The client paints different sentences for those, so this
            must not fabricate the first.
    """

    item_id: Optional[str] = None
    count: Optional[int] = None
    by_version: Optional[Dict[str, int]] = None


class InstallCountsRequest(BaseModel):
    """`POST /catalog/install-counts` body: the item ids to read counts for.

    Fields:
        ids: 1 to 1000 item ids, each the same string the per item route
            takes. The route de-duplicates and reads them 200 at a time.
    """

    ids: List[str] = Field(min_length=1, max_length=1000)


class InstallCountEntry(BaseModel):
    """One item's measured count inside :class:`InstallCountsResponse`.

    Fields:
        count: reported installs. ZERO IS REAL; an item whose count could
            not be read is left out of the map, never given a zero.
        by_version: version string to its count, or null when the hosted
            entry carried no readable map.
    """

    count: int
    by_version: Optional[Dict[str, int]] = None


class InstallCountsResponse(BaseModel):
    """`POST /catalog/install-counts` answer: only the ids that were measured.
    """

    items: Dict[str, InstallCountEntry]
