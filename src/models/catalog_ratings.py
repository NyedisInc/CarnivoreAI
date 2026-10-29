
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class RatingReview(BaseModel):
    """One rating somebody left, with the words they wrote.

    Fields:
        login: the rater's GitHub login. A handle can be renamed, so this
            is a display value and never an identity this app matches on.
        stars: 1 to 5 as the hosted api validated it, or null when the
            row carried none.
        text: the review body, already reduced to bounded plain text by
            the hosted sanitiser. Empty is a real answer: a rating with
            no words is allowed.
        updated_at: unix seconds. Null means the row carried no time,
            which renders as no date rather than as the epoch.
    """

    login: Optional[str] = None
    stars: Optional[int] = None
    text: Optional[str] = None
    updated_at: Optional[int] = None
    review_ref: Optional[str] = None
    author: Optional[str] = None
    publisher: Optional[bool] = None
    reported_installing: Optional[bool] = None
    installed_version: Optional[str] = None


class ItemRatingsResponse(BaseModel):
    """`GET /catalog/items/{item_id}/ratings`, relayed field for field.

    Fields:
        item_id: the id the hosted api echoed back.
        count: how many ratings there are. ZERO IS REAL and null means
            this server could not determine it.
        average: the mean, rounded to two decimals by the hosted api. It
            is 0 whenever ``count`` is 0, because a sum over no ratings
            has to be something, and the CLIENT is what refuses to paint
            that as a score. Relayed rather than blanked here so the
            proxy stays a proxy.
        histogram: star count as a string to how many gave it. The hosted
            api always sends all five keys.
        reviews: at most twenty, newest first. NULL IS NOT AN EMPTY LIST:
            null means the hosted answer carried no ``reviews`` key at
            all, and an empty list means it carried one and nobody has
            written anything. The client paints different sentences for
            those, so this must not fabricate the second.
    """

    item_id: Optional[str] = None
    count: Optional[int] = None
    average: Optional[float] = None
    histogram: Optional[Dict[str, int]] = None
    reviews: Optional[List[RatingReview]] = None


class RatingWriteRequest(BaseModel):
    """`PUT /catalog/items/{item_id}/rating`: the rating being given.

    ``stars`` IS DELIBERATELY UNTYPED HERE AND IS CHECKED IN THE HANDLER.
    A pydantic constraint refuses with FastAPI's own 422 shape, which
    carries no ``code`` field, and every catalog client switches on
    ``code``: a 422 would reach the screen as an unrecognised failure
    with nothing to say about it. So the field accepts what arrives and
    ``catalog_hosted_routes._safe_stars`` produces the refusal in the
    ``{"code", "detail"}`` shape the rest of this surface speaks.

    THE RANGE IS THE HOSTED API'S JOB AND IS NOT DUPLICATED. This module
    is a proxy, and the rule the item id guard already states applies
    here too: the laxer of two grammars is the one an attacker writes
    against, so there is one owner of what a valid rating is. What IS
    refused locally is a ``bool``, because that is a decision this
    server has to make anyway before putting the value into a JSON body
    it sends: in python ``True`` is an ``int`` equal to 1, so a JSON
    ``true`` would otherwise be forwarded as a one star rating nobody
    gave. The hosted validator excludes ``bool`` for the same reason.

    Fields:
        stars: 1 to 5. See above for who checks what.
        text: the words, or null. EMPTY IS A REAL ANSWER: a rating is
            allowed to be silent, and the hosted sanitiser reduces
            whatever arrives to bounded plain text before storing it.
    """

    stars: Any = None
    text: Optional[str] = None


class ItemRatingWriteResponse(BaseModel):
    """What a rating write answers, relayed field for field.

    THE SUMMARY SHAPE PLUS ONE KEY, AND NO ``reviews``. The hosted
    handlers answer the post-write totals so a screen repaints from what
    is stored rather than from what it hoped; neither carries the review
    list, and that absence is upstream's decision rather than a loss
    here. It is a SEPARATE model from :class:`ItemRatingsResponse` for
    exactly that reason: a client handed this shape as a read would see
    the missing key as "what people wrote could not be read".

    ``your_stars`` AND ``removed`` ARE EACH NULL ON THE OTHER VERB, which
    is not a defaulted value but the honest answer to a question that
    verb did not ask. A caller knows which call it made.

    Fields:
        item_id: the id the hosted api echoed back.
        count, average, histogram: the totals AFTER the write.
        your_stars: what the server recorded for this account. ``PUT``
            only. Null means the answer named none, never zero stars.
        removed: whether a rating was withdrawn. ``DELETE`` only. FALSE
            IS A REAL ANSWER and means there was nothing to withdraw,
            which is a different sentence from having removed one.
    """

    item_id: Optional[str] = None
    count: Optional[int] = None
    average: Optional[float] = None
    histogram: Optional[Dict[str, int]] = None
    your_stars: Optional[int] = None
    removed: Optional[bool] = None
