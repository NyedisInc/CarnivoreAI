
from __future__ import annotations

from typing import Mapping

from src.cplugs.huddle import lane
from src.cplugs.huddle.rules import TaskManagerForbidden

SWARM_LANE_REFUSAL = "a swarm-lane task is worked through the swarm card tools (swarm_card_start), not task_manager_update working"
NOT_SWARM_LANE_SQL = f"lane != '{lane.SWARM}'"


def refuse_swarm_lane(row: Mapping, caller_is_swarm_agent: bool) -> None:
    if row["lane"] == lane.SWARM and not caller_is_swarm_agent:
        raise TaskManagerForbidden(SWARM_LANE_REFUSAL)
