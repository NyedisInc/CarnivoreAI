
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, NamedTuple, Optional


class ToastCall(NamedTuple):

    call_id: Optional[str]
    tool: Optional[str]
    target: Optional[str]


class BlockedCall(NamedTuple):

    call_id: Optional[str]
    name: Optional[str]


@dataclass
class LaunchRec:

    key: str
    kind: str
    task_id: Optional[str]
    tool_use_id: Optional[str]
    offset: int
    at: Optional[datetime]

    def completed(self, notified: Mapping[str, int], bound: int = 0) -> bool:
        return any(i is not None and notified.get(i, -1) >= bound for i in (self.task_id, self.tool_use_id))


@dataclass(frozen=True)
class QueuedMessage:

    offset: int
    plain: bool
    chars: Optional[int]
    command_uuid: Optional[str] = None
