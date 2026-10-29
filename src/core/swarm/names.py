
from __future__ import annotations

from typing import Any, Mapping

LEADER_RANKS = ("company", "project")
_SUFFIX = " agent"


def shown_name(agent: Mapping[str, Any]) -> str:
    name = str(agent.get("display_name") or "")
    if agent.get("rank") in LEADER_RANKS and name.lower().endswith(_SUFFIX) and name[:-len(_SUFFIX)].strip():
        return name[:-len(_SUFFIX)].rstrip()
    return name
