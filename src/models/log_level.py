
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

LevelName = Literal["error", "warn", "info", "debug"]


class LogLevelState(BaseModel):
    """The server's log level in force and where it came from."""

    level: LevelName = Field(..., description="the level in force right now")
    source: Literal["setting", "env"] = Field(
        ..., description="setting: chosen in the app; env: LOG_LEVEL from .env (default info)"
    )
    env_level: LevelName = Field(..., description="the level LOG_LEVEL gives when nothing is chosen")
    choices: List[LevelName] = Field(..., description="the accepted levels, quietest first")
    expires_at: Optional[str] = Field(
        None, description="UTC time (ISO 8601) the server puts a temporary debug level back; null when none is pending"
    )


class LogLevelWrite(BaseModel):
    """Choose a level, or send null to go back to LOG_LEVEL from .env."""

    model_config = ConfigDict(extra="forbid")

    level: Optional[LevelName] = Field(..., description="error, warn, info or debug; null clears the choice")
    expires_in_s: Optional[int] = Field(
        None, ge=1, description="debug only: seconds until the server puts the previous level back; default and cap 1800"
    )

