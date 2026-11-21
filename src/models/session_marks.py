from typing import List, Optional

from pydantic import BaseModel, Field


class SkillLast(BaseModel):
    """The newest skill use of a session: its name and when (ISO 8601, or null)."""

    name: str
    at: Optional[str] = None


class AutomationMark(BaseModel):
    """The automation run that started a session (the sidebar's "auto" chip)."""

    automation_id: str
    run_id: str
    name: str


class ScheduledMark(BaseModel):
    """One scheduled thing counted in a session's Carnivore timers icon (an automation, or a plugin's scheduled item)."""

    name: str
    enabled: bool
    next_fire_at: Optional[float] = None


class MessagingMark(BaseModel):
    """This session's messaging bindings (issue #1499): the directions it is bound in and its held count."""

    directions: List[str] = Field(..., description="'in' and/or 'out', the union over its bindings")
    held: int = Field(..., description="Inbound texts held for this session (a dialog open, asleep, not running)")


class CodexHelpersMark(BaseModel):
    """Whether the Codex this row runs can start its helper programs (issue #3046, ``docs/codex-helper-check.md``).

    Mirrors ``src.core.codex_helpers.check.HelperCheck``. Null on the wrapper means NOT MEASURED (not a Codex row,
    or its version was never checked), never "all well"; a measured healthy install says ``verdict: "ok"``.
    """

    verdict: str = Field(..., description="'ok', 'blocked', 'host_failed' or 'not_applicable'")
    version: Optional[str] = Field(None, description="The checked Codex version, or null when it could not be read")
    text: Optional[str] = Field(None, description="The readable reason Codex tool calls will fail; null unless failing")
    checked_at: str = Field(..., description="ISO 8601 UTC time of the check")
