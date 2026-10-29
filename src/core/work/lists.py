
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

ALL_LIST = "all"
LIST_KEY = re.compile(r"^(all|[1-9][0-9]{0,9}|agent:[1-9][0-9]{0,9})$")
AGENT_KEY = re.compile(r"^agent:([1-9][0-9]{0,9})$")

OWNER_ALL = "all"
OWNER_PROJECT = "project"
OWNER_AGENT = "agent"


@dataclass(frozen=True)
class ListOwner:
    """Who a list belongs to. ``kind`` is :data:`OWNER_ALL`, :data:`OWNER_PROJECT` or :data:`OWNER_AGENT`; ``id`` is the project row id
    or the agent id, 0 for ``all``."""

    kind: str
    id: int


def is_valid(key: object) -> bool:
    return isinstance(key, str) and LIST_KEY.match(key) is not None


def agent_id_of(key: object) -> Optional[int]:
    match = AGENT_KEY.match(key) if isinstance(key, str) else None
    return int(match.group(1)) if match else None


def owner(key: str) -> Optional[ListOwner]:
    if not is_valid(key):
        return None
    agent = agent_id_of(key)
    if agent is not None:
        return ListOwner(OWNER_AGENT, agent)
    return ListOwner(OWNER_ALL, 0) if key == ALL_LIST else ListOwner(OWNER_PROJECT, int(key))


def order_id(key: str) -> int:
    agent = agent_id_of(key)
    return agent if agent is not None else int(key) if key.isdigit() else 0
