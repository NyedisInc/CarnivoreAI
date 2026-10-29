
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from src.cplugs.sdk import ports

NAME = "huddle.devtools"


class TaskManagerOff(RuntimeError):
    pass


class DevToolsPort(Protocol):

    async def projects(self) -> List[Dict[str, Any]]:
        pass

    async def tasks(self, *, project: Optional[str] = None, status: Optional[str] = None, group: Optional[str] = None,
                    tag: Optional[str] = None, kind: Optional[str] = None) -> Dict[str, Any]:
        pass

    async def resolve(self, *, project: Optional[str] = None, groups: Optional[List[str]] = None, items: Optional[List[int]] = None) -> Dict[str, Any]:
        pass


def get() -> DevToolsPort:
    port = ports.get(NAME)
    if port is None:
        raise TaskManagerOff("the task manager is off, so it cannot be read")
    return port
