
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SleepHoldInfo(BaseModel):
    """Why a session is kept awake because something of its is scheduled or running.

    Joe (ccsliinc), 2026-10-01: a live timer, a running subagent or an open
    background shell keeps a session from auto-sleeping, coffee cup or not,
    because sleeping kills what lives inside its claude.
    """

    reasons: List[str] = Field(
        default_factory=list,
        description="timers | subagents | background | parked | unmeasured, one or more",
    )
    text: str = Field("", description="one plain sentence, e.g. 'kept awake: 2 live timers, next 18:52'")


class SleepHoldEntry(SleepHoldInfo):

    session: str = Field(..., description="tmux name of the session kept awake")


class AutoSleepState(BaseModel):
    """The auto-sleep settings and who is kept awake, as every surface reads them."""

    enabled: bool = Field(..., description="whether idle agent sessions are put to sleep")
    idle_minutes: int = Field(
        ..., description="minutes a session must read idle, continuously, before it is slept"
    )
    unread_blocks_sleep: bool = Field(
        False,
        description=(
            "true keeps a session with the unread mark awake; false lets it sleep "
            "after unread_idle_minutes of idle, keeping its unread mark"
        ),
    )
    unread_idle_minutes: int = Field(
        60,
        description="idle minutes an unread session needs before it is slept; used only when unread_blocks_sleep is false",
    )
    min_idle_minutes: int = Field(..., description="the smallest idle_minutes accepted")
    max_idle_minutes: int = Field(..., description="the largest idle_minutes accepted")
    keep_awake: List[str] = Field(
        default_factory=list,
        description=(
            "tmux names of the live, undeleted sessions whose keep-awake flag is on, "
            "resolved from the stored session uuids at read time"
        ),
    )
    keep_awake_session_uuids: List[str] = Field(
        default_factory=list, description="the stored keep-awake list, by durable session uuid"
    )
    holding: List[SleepHoldEntry] = Field(
        default_factory=list,
        description=(
            "sessions the last auto-sleep pass kept awake because a timer, "
            "subagent or background shell is live (or could not be measured), "
            "each with the reason; only sessions idle long enough to be slept appear"
        ),
    )
    mac_awake: bool = Field(
        ...,
        description=(
            "whether this server currently holds a macOS idle-sleep assertion "
            "(issue #617); true while any session has keep-awake on and the "
            "caffeinate child is running, false otherwise or when caffeinate "
            "is unavailable on this build"
        ),
    )


class AutoSleepWrite(BaseModel):
    """Body of ``PUT /auto-sleep``. An omitted field is left unchanged."""

    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = None
    idle_minutes: Optional[int] = None
    unread_blocks_sleep: Optional[bool] = None
    unread_idle_minutes: Optional[int] = None


class KeepAwakeWrite(BaseModel):
    """Body of ``PUT /auto-sleep/keep-awake``: name the session ONE way.

    ``session_uuid`` is the durable key and is what is stored; ``tmux_name``
    is resolved to one (the live row carrying that name, else the newest),
    because the surfaces that draw the toggle hold a tmux name.
    """

    model_config = ConfigDict(extra="forbid")

    keep_awake: bool
    session_uuid: Optional[str] = None
    tmux_name: Optional[str] = None
