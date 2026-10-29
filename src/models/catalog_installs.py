
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

    Fields:
        items: id to :class:`InstallCountEntry`. A MISSING ID MEANS NOT
            MEASURED (unknown to the catalog, or its chunk failed), never
            "nobody has installed it".
    """

    items: Dict[str, InstallCountEntry]
