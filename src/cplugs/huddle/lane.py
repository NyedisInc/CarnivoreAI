
from __future__ import annotations

from typing import Collection, Mapping

from src.cplugs.huddle import rules

TASK_MANAGER = "task_manager"
SWARM = "swarm"
LANES = (TASK_MANAGER, SWARM)

SWARM_ORIGINS = ("agent", "spawn")
AGENT_LIST_PREFIX = "agent:"
REFUSED_CODE = "task_manager_lane"


def from_origin(card_origin: str) -> str:
    return SWARM if card_origin.partition(":")[0] in SWARM_ORIGINS else TASK_MANAGER


def for_new(*, list_key: str, created_key: str = "", swarm_ref: str = "", card_origin: str = "") -> str:
    if swarm_ref or created_key == rules.SWARM_KEY or list_key.startswith(AGENT_LIST_PREFIX):
        return SWARM
    return from_origin(card_origin)


def is_task_manager(row: Mapping[str, object]) -> bool:
    return row["lane"] == TASK_MANAGER




def hides_swarm(list_key: str | None, include_swarm: bool) -> bool:
    return not include_swarm and not (list_key or "").startswith(AGENT_LIST_PREFIX)


def visible_sql(alias: str = "") -> str:
    return f"{alias + '.' if alias else ''}lane = '{TASK_MANAGER}'"


def merge_order(live: list[tuple[int, str]], ids: list[int], settled: Collection[int] = ()) -> list[int] | None:
    named = set(ids)
    for candidate in ({i for i, _ in live}, {i for i, row_lane in live if row_lane == TASK_MANAGER}):
        if named <= candidate and (candidate - set(settled)) <= named:
            order = iter(ids)
            return [next(order) if i in named else i for i, _ in live]
    return None
