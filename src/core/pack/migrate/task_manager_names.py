
from __future__ import annotations

from typing import Any, Mapping

RETIRED_STATES = {"approved": "done", "approved_with_note": "done", "waiting_install": "waiting", "back_burner": "todo",
                  "done_by_claude": "review"}
WIRE_STATES = {"done": "approved", "waiting": "waiting_install", "todo": "back_burner", "review": "done_by_claude"}
DONE_WITH_NOTE = "approved_with_note"
STATE_ARGS = ("state", "fork_state", "parent_state", "to_state")

TASK_MANAGER, SWARM = "task_manager", "swarm"
SWARM_KEY = "swarm"
SWARM_ORIGINS = ("agent", "spawn")
AGENT_LIST_PREFIX = "agent:"


def current_state(value: Any) -> Any:
    return RETIRED_STATES.get(value, value) if isinstance(value, str) else value


def wire_state(state: Any, note: Any = "") -> Any:
    if state == "done" and str(note or "").strip():
        return DONE_WITH_NOTE
    return WIRE_STATES.get(state, state) if isinstance(state, str) else state


def wire_state_args(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: wire_state(v) if k in STATE_ARGS else wire_state_args(v) for k, v in value.items()}
    if isinstance(value, list):
        return [wire_state_args(v) for v in value]
    return value


def lane_of(item: Mapping[str, Any], list_key: str) -> str:
    if item.get("swarm_ref") or item.get("created_key") == SWARM_KEY or list_key.startswith(AGENT_LIST_PREFIX):
        return SWARM
    return SWARM if str(item.get("card_origin") or "").partition(":")[0] in SWARM_ORIGINS else TASK_MANAGER
