
from __future__ import annotations

from typing import Annotated, List, Literal, Optional, Tuple

from pydantic import Field, StringConstraints, field_validator

from .catalog_doc import _Doc

WarningKind = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]

ReviewVerdict = Literal["clean", "flagged", "blocked"]


class ReviewWarning(_Doc):

    kind: WarningKind
    detail: str = Field(..., min_length=1)
    file: Optional[str] = None
    line: Optional[int] = None


class ReviewOverride(_Doc):

    reason: str = Field(..., min_length=1)
    by: Optional[str] = None
    at: Optional[str] = None

    @field_validator("reason")
    @classmethod
    def _reason_says_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an override must carry a reason")
        return value


class ReviewBlock(_Doc):

    status: Literal["reviewed", "unavailable"]
    summary: Optional[str] = None
    warnings: Optional[List[ReviewWarning]] = None
    model: Optional[str] = None
    reviewed_at: Optional[str] = None
    verdict: Optional[ReviewVerdict] = None
    override: Optional[ReviewOverride] = None


INSTRUCTIONS_WRITE_KIND = "instructions_write"


def review_writes_instructions(review: Optional[ReviewBlock]) -> bool:
    if review is None or review.status != "reviewed" or not review.warnings:
        return False
    return any(w.kind == INSTRUCTIONS_WRITE_KIND for w in review.warnings)


MAX_INSTRUCTIONS_DETAILS = 3
MAX_INSTRUCTIONS_DETAIL_CHARS = 200


def review_instructions_details(
    review: Optional[ReviewBlock],
) -> Tuple[List[str], int]:
    if review is None or review.status != "reviewed" or not review.warnings:
        return [], 0
    found = [w for w in review.warnings if w.kind == INSTRUCTIONS_WRITE_KIND]
    details: List[str] = []
    for warning in found:
        text = (warning.detail or "").strip()
        if not text or len(details) >= MAX_INSTRUCTIONS_DETAILS:
            continue
        if len(text) > MAX_INSTRUCTIONS_DETAIL_CHARS:
            text = text[: MAX_INSTRUCTIONS_DETAIL_CHARS - 3] + "..."
        details.append(text)
    return details, len(found) - len(details)
