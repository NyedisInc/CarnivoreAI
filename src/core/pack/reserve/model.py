
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

LEVEL_IN_USE = "in_use"
LEVEL_AWAY = "away"
SOURCE_SCHEDULE = "schedule"
SOURCE_KEYBOARD = "keyboard"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Level(BaseModel):
    """One reserve level: the share of cpu and memory kept for the owner."""

    model_config = ConfigDict(extra="forbid")

    cpu_pct: int = Field(ge=0, le=90)
    mem_pct: int = Field(ge=0, le=90)


class Schedule(BaseModel):
    """When the in-use level holds: local ``in_use_from`` to ``in_use_to`` on ``days`` (0 is Monday). A window that
    ends before it starts wraps past midnight."""

    model_config = ConfigDict(extra="forbid")

    in_use_from: str = "08:00"
    in_use_to: str = "23:00"
    days: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6], max_length=7)

    @field_validator("in_use_from", "in_use_to")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        if not _HHMM.match(value):
            raise ValueError("a time is HH:MM, 24 hour")
        return value

    @field_validator("days")
    @classmethod
    def _days(cls, value: List[int]) -> List[int]:
        if any(not isinstance(d, int) or d < 0 or d > 6 for d in value):
            raise ValueError("days are 0 (Monday) to 6 (Sunday)")
        return sorted(set(value))


class KeyboardRule(BaseModel):
    """Hold the in-use level while the machine had keyboard or mouse input in the last ``idle_minutes``."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    idle_minutes: int = Field(default=10, ge=1, le=240)


class ReserveConfig(BaseModel):
    """The whole ``reserve`` document of one machine."""

    model_config = ConfigDict(extra="forbid")

    in_use: Level = Field(default_factory=lambda: Level(cpu_pct=30, mem_pct=20))
    away: Level = Field(default_factory=lambda: Level(cpu_pct=10, mem_pct=10))
    schedule: Schedule = Field(default_factory=Schedule)
    keyboard_rule: KeyboardRule = Field(default_factory=KeyboardRule)


def from_dict(raw: Any) -> ReserveConfig:
    if not isinstance(raw, dict):
        return ReserveConfig()
    try:
        return ReserveConfig(**raw)
    except (TypeError, ValueError):
        return ReserveConfig()


def merged(current: ReserveConfig, patch: Dict[str, Any]) -> ReserveConfig:
    base = current.model_dump()
    for key, value in patch.items():
        if key not in base:
            raise ValueError(f"unknown reserve field {key}")
        base[key] = {**base[key], **value} if isinstance(value, dict) else value
    return ReserveConfig(**base)


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def in_schedule(config: ReserveConfig, now: datetime) -> bool:
    start, end = _minutes(config.schedule.in_use_from), _minutes(config.schedule.in_use_to)
    minute, day = now.hour * 60 + now.minute, now.weekday()
    days = config.schedule.days
    if start == end:
        return day in days
    if start < end:
        return day in days and start <= minute < end
    return (day in days and minute >= start) or (((day - 1) % 7) in days and minute < end)


def active(config: ReserveConfig, now: datetime, hid_idle_seconds: Optional[float]) -> Dict[str, Any]:
    by_schedule = in_schedule(config, now)
    rule = config.keyboard_rule
    at_keys = (rule.enabled and hid_idle_seconds is not None and hid_idle_seconds < rule.idle_minutes * 60)
    in_use = by_schedule or at_keys
    level = config.in_use if in_use else config.away
    return {"level": LEVEL_IN_USE if in_use else LEVEL_AWAY, "cpu_pct": level.cpu_pct, "mem_pct": level.mem_pct,
            "source": SOURCE_KEYBOARD if (at_keys and not by_schedule) else SOURCE_SCHEDULE}
