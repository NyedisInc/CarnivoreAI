from typing import Optional

from pydantic import BaseModel, Field


class SkillFireOut(BaseModel):
    """One recorded skill use, as ``GET /sessions/{id}/skill-fires`` lists it."""

    skill: str
    at: Optional[str] = None
    source: str = Field(description="tool_use | slash | inferred (a codex SKILL.md read)")
    harness: str
    profile: str


class SessionSkillFires(BaseModel):
    """A session's skill fires: the count and the newest uses, newest first."""

    state: str = Field(description="measured | not_measured | unsupported")
    fired: Optional[int] = None
    recent: list[SkillFireOut] = Field(default_factory=list)


class SkillUsage(BaseModel):
    """One skill's local fire counts. Null counts mean not measured, never zero."""

    skill: str
    state: str = Field(description="measured | not_measured")
    fired_7d: Optional[int] = None
    fired_30d: Optional[int] = None
    fired_90d: Optional[int] = None
