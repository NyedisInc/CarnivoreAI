
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AutopsySpan(BaseModel):
    """One recent fire span: counts and one short redacted excerpt, never a message body."""

    fired_at: Optional[str] = None
    session: str
    tool_calls: int
    tool_errors: int
    interrupted: bool
    tokens: Optional[int] = None
    correction: Optional[bool] = None
    next_excerpt: Optional[str] = None
    ended: str = Field(description="human | fire | eof | cap")
    categories: List[str] = Field(default_factory=list)
    digest: Optional[str] = Field(default=None, description="the installed digest the fire ran under, or null when not recorded")


class SkillAutopsy(BaseModel):
    """``GET /skills/{name}/autopsy``: what followed a skill's fires on this mac."""

    skill: str
    days: int
    state: str = Field(description="measured | not_measured")
    fires: Optional[int] = None
    spans_measured: Optional[int] = None
    tool_calls: Optional[int] = None
    tool_errors: Optional[int] = None
    interrupts: Optional[int] = None
    corrections: Optional[int] = None
    corrections_measured: Optional[int] = None
    tokens_total: Optional[int] = None
    categories: Dict[str, int] = Field(default_factory=dict)
    undisclosed: Optional[List[str]] = Field(
        default=None, description="observed risk categories the installed version's review and allowed-tools did not disclose; null = cannot judge")
    recent: List[AutopsySpan] = Field(default_factory=list)


class DriftView(BaseModel):
    """Sentinel's verdict on one installed row."""

    state: str = Field(description="clean | drifted | missing | unknown")
    changed_files: Optional[List[str]] = Field(default=None, description="null = not measured")
    checked_at: Optional[float] = None


class ForkRequest(BaseModel):
    """Body of ``PUT /catalog/installed/{install_id}/fork``."""

    forked: bool
