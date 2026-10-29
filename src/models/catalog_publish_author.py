
from __future__ import annotations

from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field


class AppealRequest(BaseModel):
    """`POST /catalog/submissions/{id}/appeal`: the author's note on a rejected submission (the host bounds it to 1000)."""

    text: str = Field(min_length=1, max_length=1000)


class SubmissionActionResponse(BaseModel):
    """What the host answers to an appeal or a withdraw: the id, the new status and, for an appeal, the appeals used."""

    submission_id: str = Field(max_length=64)
    status: str = Field(max_length=32)
    appeals: Optional[int] = None


class LimitsResponse(BaseModel):
    """`GET /catalog/submissions/limits`: the host's own numbers for this account today."""

    per_day: Optional[int] = None
    used_today: Optional[int] = None
    new_account: bool = False
    new_account_per_day: Optional[int] = None
    new_account_days: Optional[int] = None
    open_max: Optional[int] = None
    open_now: Optional[int] = None
    cooldown_until: str = Field(default="", max_length=40)
    strikes: Optional[int] = None
    strikes_max: Optional[int] = None
    appeals_max: Optional[int] = None
    media_per_day: Optional[int] = None
    media_used_today: Optional[int] = None


class RulesKind(BaseModel):
    """One page tab and whether the front door takes that kind from an ordinary account."""

    kind: str
    open: bool


class RulesResponse(BaseModel):
    """`GET /catalog/publish/rules`: open state per page tab, the hero image rules and the per-kind caps."""

    kinds: List[RulesKind]
    caps: Dict[str, Union[int, float]]
