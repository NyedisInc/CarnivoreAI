
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

UNATTENDED_PHRASE = "run unattended with no permission prompts"


class AutomationCreate(BaseModel):
    """``POST /automations``: a name, a cron, one target and how the owner hears of runs.

    ``acknowledge_unattended`` must equal :data:`UNATTENDED_PHRASE` when the target is an agent with ``permission: unattended``.
    """

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    cron: str = Field(min_length=1, max_length=120)
    target: Dict[str, Any]
    delivery: Optional[Dict[str, Any]] = None
    enabled: bool = True
    acknowledge_unattended: Optional[str] = None
    description: str = Field(default="", max_length=500)
    project_id: Optional[int] = Field(default=None, ge=1)
    misfire: Literal["skip", "run_once"] = "run_once"
    retry_max: int = Field(default=0, ge=0, le=3)
    retry_backoff_s: int = Field(default=300, ge=60, le=3600)
    max_runtime_s: Optional[int] = Field(default=None, ge=60, le=86400)


CONTRACT_PATCH_FIELDS = ("description", "project_id", "misfire", "retry_max", "retry_backoff_s", "max_runtime_s")


class AutomationPatch(BaseModel):
    """``PATCH /automations/{id}``: the revision the editor read, plus only the fields that change."""

    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    cron: Optional[str] = Field(default=None, min_length=1, max_length=120)
    target: Optional[Dict[str, Any]] = None
    delivery: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    acknowledge_unattended: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=500)
    project_id: Optional[int] = Field(default=None, ge=1)
    misfire: Optional[Literal["skip", "run_once"]] = None
    retry_max: Optional[int] = Field(default=None, ge=0, le=3)
    retry_backoff_s: Optional[int] = Field(default=None, ge=60, le=3600)
    max_runtime_s: Optional[int] = Field(default=None, ge=60, le=86400)


class SchedulePreview(BaseModel):
    """``POST /automations/schedule/preview``: a cron string to check."""

    model_config = ConfigDict(extra="forbid")
    cron: str = Field(min_length=1, max_length=120)



class ScheduleParse(BaseModel):
    """``POST /automations/schedule/parse``: a sentence and the caller's IANA zone name."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=1, max_length=64)