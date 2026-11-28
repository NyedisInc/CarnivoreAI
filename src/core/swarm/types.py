
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.plugins.sdk.swarm import SwarmError


class CreateRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class BodyIdentity:

    session_id: str
    row_id: int
    session_uuid: str
    tmux_name: str
    tmux_epoch: Optional[int]


class TurnOnError(SwarmError):
    pass


class ProjectMissing(TurnOnError):
    pass
