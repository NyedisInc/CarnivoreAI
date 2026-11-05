
from __future__ import annotations

from typing import Any, Mapping

RETIRED_STATES = {"approved": "done", "approved_with_note": "done", "waiting_install": "waiting", "back_burner": "todo",
                  "done_by_claude": "review"}

TASK_MANAGER, SWARM = "task_manager", "swarm"
SWARM_KEY = "swarm"
SWARM_ORIGINS = ("agent", "spawn")
AGENT_LIST_PREFIX = "agent:"


def current_state(value: Any) -> Any:
    return RETIRED_STATES.get(value, value) if isinstance(value, str) else value


def lane_of(item: Mapping[str, Any], list_key: str) -> str:
    if item.get("swarm_ref") or item.get("created_key") == SWARM_KEY or list_key.startswith(AGENT_LIST_PREFIX):
        return SWARM
    return SWARM if str(item.get("card_origin") or "").partition(":")[0] in SWARM_ORIGINS else TASK_MANAGER
